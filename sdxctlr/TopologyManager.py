# Copyright 2016 - Sean Donovan
# AtlanticWave/SDX Project


from lib.Singleton import SingletonMixin
from threading import Lock
import networkx as nx
import json
from lib.SteinerTree import make_steiner_tree

#FIXME: This shouldn't be hard coded.
MANIFEST_FILE = '../manifests/localcontroller.manifest'

class TopologyManagerError(Exception):
    ''' Parent class as a catch-all for other errors '''
    pass

class TopologyManager(SingletonMixin):
    ''' The TopologyManager handles the topology of the network. Initially, this
        will be very simple, as there will only be three switches, and ~100 
        ports total.
        It may be used to manage virtual topologies (VLANs, for instance) as 
        well.
        It will likely use NetworkX for handling large graphs, as well as for 
        its JSON generation abilities.
        Singleton. '''
    
    def __init__(self, topology_file=MANIFEST_FILE):
        # Initialize topology
        self.topo = nx.Graph()
        self.lcs = []         # This probably should end up as a list of dicts.

        # Initialize topology lock.
        self.topolock = Lock()

        #FIXME: Static topology right now.
        self._import_topology(topology_file)

    def get_topology(self):
        ''' Returns the topology with all details. 
            This is a NetworkX graph:
            https://networkx.readthedocs.io/en/stable/reference/index.html '''
        return self.topo
    
    def get_lcs(self):
        ''' Returns the list of valid LocalControllers. '''
        return self.lcs

    def register_for_topology_updates(self, callback):
        ''' callback will be called when there is a topology update. callback 
            must accept a topology as its only parameter. '''
        # Not used now, as only using static topology.
        pass 
        
    def unregister_for_topology_updates(self, callback):
        ''' Remove callback from list of callbacks to be called when there's a 
            topology update. '''
        # Not used now, as only using static topology.
        pass
    

    def _import_topology(self, manifest_filename):
        with open(manifest_filename) as data_file:
            data = json.load(data_file)

        for unikey in data['endpoints'].keys():
            # All the other nodes
            key = str(unikey)
            endpoint = data['endpoints'][key]
            with self.topolock:
                if not self.topo.has_node(key):
                    self.topo.add_node(key)
                for k in endpoint:
                    if type(endpoint[k]) == int:
                        self.topo.node[key][k] = int(endpoint[k])
                    self.topo.node[key][k] = str(endpoint[k])
                    

        for key in data['localcontrollers'].keys():
            # Generic per-location information that applies to all switches at
            # a location.
            # FIXME: Everything's wrapped as a str or int because Unicode.
            entry = data['localcontrollers'][key]
            shortname = str(entry['shortname'])
            location = str(entry['location'])
            lcip = str(entry['lcip'])
            org = str(entry['operatorinfo']['organization'])
            administrator = str(entry['operatorinfo']['administrator'])
            contact = str(entry['operatorinfo']['contact'])
            
            # Add shortname to the list of valid LocalControllers
            self.lcs.append(shortname)

            # Fill out topology
            with self.topolock:
                # Add local controller
                self.topo.add_node(key)
                self.topo.node[key]['type'] = "localcontroller"
                self.topo.node[key]['shortname'] = shortname
                self.topo.node[key]['location'] = location
                self.topo.node[key]['ip'] = lcip
                self.topo.node[key]['org'] = org
                self.topo.node[key]['administrator'] = administrator
                self.topo.node[key]['contact'] = contact
                self.topo.node[key]['internalconfig'] = entry['internalconfig']

                # Add switches to the local controller. Actually happens after
                # the switches are handled.
                switch_list = []

                # Switches for that LC
                for switchinfo in entry['switchinfo']:
                    name = str(switchinfo['name'])
                    # Node may be implicitly declared, check this first.
                    if not self.topo.has_node(name):
                        self.topo.add_node(name)

                    # Add switch to LC list. This will be added at the end.
                    switch_list.append(name)
                    
                    # Per switch info, gets added to topo
                    self.topo.node[name]['friendlyname'] = str(switchinfo['friendlyname'])
                    self.topo.node[name]['dpid'] = int(switchinfo['dpid'], 0) #0 guesses base.
                    self.topo.node[name]['ip'] = str(switchinfo['ip'])
                    self.topo.node[name]['brand'] = str(switchinfo['brand'])
                    self.topo.node[name]['model'] = str(switchinfo['model'])
                    self.topo.node[name]['locationshortname'] = shortname
                    self.topo.node[name]['location'] = location
                    self.topo.node[name]['lcip'] = lcip
                    self.topo.node[name]['lcname'] = key
                    self.topo.node[name]['org'] = org
                    self.topo.node[name]['administrator'] = administrator
                    self.topo.node[name]['contact'] = contact
                    self.topo.node[name]['type'] = "switch"

                    # Other fields that may be of use
                    self.topo.node[name]['vlans_in_use'] = []

                    self.topo.node[name]['internalconfig'] = switchinfo['internalconfig']

                    # Add the links
                    for port in switchinfo['portinfo']:
                        portnumber = int(port['portnumber'])
                        speed = int(port['speed'])
                        destination = str(port['destination'])

                        # If link already exists
                        if not self.topo.has_edge(name, destination):
                            self.topo.add_edge(name,
                                               destination,
                                               weight=speed)
                        # Set the port number for the current location. The dest
                        # port should be set when the dest side has been run.
                        self.topo.edge[name][destination][name] = portnumber

                        # Other fields that may be of use
                        self.topo.edge[name][destination]['vlans_in_use'] = []
                        self.topo.edge[name][destination]['bw_in_use'] = 0
                # Once all the switches have been looked at, add them to the
                # LC
                self.topo.node[key]['switches'] = switch_list

    # -----------------
    # Generic functions
    # -----------------

    def reserve_bw(self, node_pairs, bw):        
        ''' Generic method for reserving bandwidth based on pairs of nodes. '''
        #FIXME: Should there be some more accounting on this? Reference to the
        #structure reserving the bw?        
        with self.topolock:
            # Check to see if we're going to go over the bandwidth of the edge
            for (node, nextnode) in node_pairs:
                bw_in_use = self.topo.edge[node][nextnode]['bw_in_use']
                bw_available = int(self.topo.edge[node][nextnode]['weight'])

                if (bw_in_use + bw) > bw_available:
                    raise TopologyManagerError("BW available on path %s:%s is %s. In use %s, new reservation of %s" % (node, nextnode, bw_available, bw_in_use, bw))

            # Add bandwidth reservation
            for (node, nextnode) in node_pairs:
                self.topo.edge[node][nextnode]['bw_in_use'] += bw

    def unreserve_bw(self, node_pairs, bw):
        ''' Generic method for removing bw reservation based on pairs of nodes. 
        '''
        with self.topolock:
            # Check to see if we've removed too much
            for (node, nextnode) in node_pairs:
                bw_in_use = self.topo.edge[node][nextnode]['bw_in_use']

                if bw > bw_in_use:
                    raise TopologyManagerError("BW in use on path %s:%s is %s. Trying to remove %s" % (node, nextnode, bw_in_use, bw))

            # Remove bw from path
            for (node, nextnode) in node_pairs:
                self.topo.edge[node][nextnode]['bw_in_use'] -= bw

    def reserve_vlan(self, nodes, node_pairs, vlan):
        ''' Generic method for reserving VLANs on given nodes and paths based on
            nodes and pairs of nodes. '''
        #FIXME: Should there be some more accounting on this? Reference to the
        #structure reserving the vlan?
        # FIXME: This probably has some issues with concurrency.

        with self.topolock:
            # Make sure the path is clear -> very similar to find_vlan_on_path
            for node in nodes:
                if vlan in self.topo.node[node]['vlans_in_use']:
                    raise TopologyManagerError("VLAN %d is already reserved on node %s" % (vlan, node))

            for (node, nextnode) in node_pairs:
                if vlan in self.topo.edge[node][nextnode]['vlans_in_use']:
                    raise TopologyManagerError("VLAN %d is already reserved on path %s:%s" % (vlan, node, nextnode))                    

            # Walk through the nodess and reserve it
            for node in nodes:
                self.topo.node[node]['vlans_in_use'].append(vlan)

            # Walk through the edges and reserve it
            for (node, nextnode) in node_pairs:
                self.topo.edge[node][nextnode]['vlans_in_use'].append(vlan)
    
    def unreserve_vlan(self, nodes, node_pairs, vlan):
        ''' Generic method for unreserving VLANs on given nodes and paths based 
            on nodes and pairs of nodes. '''
        with self.topolock:
            # Make sure it's already reserved on the given path:
            for node in nodes:
                if vlan not in self.topo.node[node]['vlans_in_use']:
                    raise TopologyManagerError("VLAN %d is not reserved on node %s" % (vlan, node))

            for (node, nextnode) in node_pairs:
                if vlan not in self.topo.edge[node][nextnode]['vlans_in_use']:
                    raise TopologyManagerError("VLAN %d is not reserved on path %s:%s" % (vlan, node, nextnode))

            # Walk through the nodes and unreserve it
            for node in nodes:
                self.topo.node[node]['vlans_in_use'].remove(vlan)

            # Walk through the edges and unreserve it
            for (node, nextnode) in node_pairs:
                self.topo.edge[node][nextnode]['vlans_in_use'].remove(vlan)

    # --------------
    # Path functions
    # --------------

    def reserve_vlan_on_path(self, path, vlan):
        ''' Marks a VLAN in use on a provided path. Raises an error if the VLAN
            is in use at the time at any location. '''
        node_pairs = zip(path[0:-1], path[1:])
        self.reserve_vlan(path, node_pairs, vlan)
        
    def unreserve_vlan_on_path(self, path, vlan):
        ''' Removes reservations on a given path for a given VLAN. '''
        node_pairs = zip(path[0:-1], path[1:])
        self.unreserve_vlan(path, node_pairs, vlan)

    def reserve_bw_on_path(self, path, bw):
        ''' Reserves a specified amount of bandwidth on a given path. Raises an
            error if the bandwidth is not available at any part of the path. '''
        node_pairs = zip(path[0:-1], path[1:])
        self.reserve_bw(node_pairs, bw)
        
    def unreserve_bw_on_path(self, path, bw):
        ''' Removes reservations on a given path for a given amount of
            bandwidth. '''
        node_pairs = zip(path[0:-1], path[1:])
        self.unreserve_bw(node_pairs, bw)

    def find_vlan_on_path(self, path):
        ''' Finds a VLAN that's not being used at the moment on a provided path.
            Returns an available VLAN if possible, None if none are available on
            the submitted path.
        '''
        selected_vlan = None
        with self.topolock:
            for vlan in range(1,4089):
                # Check each point on the path
                on_path = False
                for point in path:
                    if self.topo.node[point]["type"] == "switch":
                        if vlan in self.topo.node[point]['vlans_in_use']:
                            on_path = True
                            break
                    
                if on_path:
                    continue

                # Check each edge on the path
                for (node, nextnode) in zip(path[0:-1], path[1:]):
                    if vlan in self.topo.edge[node][nextnode]['vlans_in_use']:
                        on_path = True
                        break
                    
                if on_path:
                    continue

                # If all good, set selected_vlan
                selected_vlan = vlan
                break

        return selected_vlan

    def find_valid_path(self, src, dst, bw=None):
        ''' Find a path that is currently valid based on a contstraint. 
            Right now, the only constraint is bandwidth. '''

        # Get possible paths
        #FIXME: NetworkX has multiple methods for getting paths. Shortest and
        # all possible paths:
        # https://networkx.readthedocs.io/en/stable/reference/generated/networkx.algorithms.shortest_paths.generic.all_shortest_paths.html
        # https://networkx.readthedocs.io/en/stable/reference/generated/networkx.algorithms.simple_paths.all_simple_paths.html
        # May need to use *both* algorithms. Starting with shortest paths now.
        list_of_paths = nx.all_shortest_paths(self.topo,
                                              source=src,
                                              target=dst)

        for path in list_of_paths:
            # For each path, check that a VLAN is available
            vlan = self.find_vlan_on_path(path)
            if vlan == None:
                continue

            enough_bw = True
            for (node, nextnode) in zip(path[0:-1], path[1:]):
                # For each edge on the path, check that bw is available.
                bw_in_use = self.topo.edge[node][nextnode]['bw_in_use']
                bw_available = int(self.topo.edge[node][nextnode]['weight'])

                if (bw_in_use + bw) > bw_available:
                    enough_bw = False
                    break
                
            # If all's good, return the path to the caller
            if enough_bw:
                return path
        
        # No path return
        return None

    
    # --------------
    # Tree functions
    # --------------

    def reserve_vlan_on_tree(self, tree, vlan):
        ''' Marks a VLAN in use on a provided tree (nx graph). Raises an error if
            the VLAN is in use at the time at any location. '''
        self.reserve_vlan(tree.nodes(), tree.edges(), vlan)
        
    def unreserve_vlan_on_tree(self, tree, vlan):
        ''' Removes reservations on a given tree (nx graph) for a given VLAN. '''
        self.unreserve_vlan(tree.nodes(), tree.edges(), vlan)

    def reserve_bw_on_tree(self, tree, bw):
        ''' Reserves a specified amount of bandwidth on a given tree (nx graph). 
            Raises an error if the bandwidth is not available at any part of the 
            tree. '''
        self.reserve_bw(tree.edges(), bw)
        
    def unreserve_bw_on_tree(self, tree, bw):
        ''' Removes reservations on a given tree (nx graph) for a given amount of
            bandwidth. '''
        self.unreserve_bw(tree.edges(), bw)

    def find_vlan_on_tree(self, tree):
        ''' Tree version of find_vlan_on_path(). Finds a VLAN that's not being
            used at the moment on a provivded path. Returns an available VLAN if
            possible, None if none are available on the submitted tree. '''
        selected_vlan = None
        with self.topolock:
            for vlan in range(1,4089):
                # Check each point on the path
                on_path = False
                for node in tree.nodes():
                    if self.topo.node[node]["type"] == "switch":
                        if vlan in self.topo.node[node]['vlans_in_use']:
                            on_path = True
                            break
                    
                if on_path:
                    continue

                # Check each edge on the path
                for (node, nextnode) in tree.edges():
                    if vlan in self.topo.edge[node][nextnode]['vlans_in_use']:
                        on_path = True
                        break
                    
                if on_path:
                    continue

                # If all good, set selected_vlan
                selected_vlan = vlan
                break

        return selected_vlan

    def find_valid_steiner_tree(self, nodes, bw=None):
        ''' Finds a Steiner tree connecting all the nodes in 'nodes' together. 
            Uses a library containing Kou's algorithm to find one. 
            Returns a graph, from with .nodes() and .edges() can be used
            to call other functions. '''

        #FIXME: need to accomodate inability to find appropriate amount of
        #bandwidth. Take existing topology, copy it, and delete the edge with
        #a problem, then rerun Kou's algorithm.

        # Prime the topology to use
        topo = self.topo
        # Loop through, trying to make a valid Steiner tree that has available
        # bandwidth. This will either return something valid, or will blow up
        # due to a path not existing and will return nothing.
        # timeout is a just-in-case measure
        timeout = len(topo.edges())
        while(timeout > 0):
            timeout -= 1
            
            try:
                tree = make_steiner_tree(self.topo, nodes)
            except ValueError:
                raise
            except nx.exception.NetworkXNoPath:
                #FIXME: log something here.
                return None

            # Check if enough bandwidth is available
            enough_bw = True
            for (node, nextnode) in tree.edges():
                # For each edge on the path, check that bw is available.
                bw_in_use = self.topo.edge[node][nextnode]['bw_in_use']
                bw_available = int(self.topo.edge[node][nextnode]['weight'])

                if bw is not None and (bw_in_use + bw) > bw_available:
                    enough_bw = False
                    # Remove the edge that doesn't have enough bw and try again
                    topo.remove_edge(node, nextnode)
                    break
            if not enough_bw:
                continue
                

            # Check if VLAN is available
            selected_vlan = self.find_vlan_on_tree(tree)
            if selected_vlan == None:
                #FIXME: how to handle this?
                pass
 

            # Has BW and VLAN available, return it.
            return tree
            
