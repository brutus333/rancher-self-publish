#!/usr/bin/env python
import os
import simpleyaml
import urllib2
import json
import base64
import sys
import bigsuds
import logging
import time

# BigIP F5 datagroup list manipulation
def find_datagroup_list(dgc,partition,description):
    result = dgc.get_string_class(['/%s/%s' % (partition,description)])
    if not result[0]['members']:
        return False
    else:
        return result    

def edit_datagroup_list(dgc,dgl,mdv):
    try:
        dgc.add_string_class_member(dgl)
    except Exception, e:
        print e
        sys.exit(3)
    try:
        dgc.set_string_class_member_data_value(dgl,mdv)
    except Exception,e:
        print e
        sys.exit(3)

# BigIP F5 route domain functions
def get_rd_id(rd,description):
    return  [ rd.get_list()[i] for i,x in enumerate(rd.get_description(rd.get_list())) if x==description ][0].split("/")[2]

# BigIP F5 pool & pool members manipulation

def pool_exists(b,pool,description):
    return [ True for x in pool.get_list() if x.split("/")[2]==description ]

def find_pool_ids(pool,partition,prefix):
    reg = re.compile('(/%s/%s)([0-9]*).*' % (partition,prefix))
    result = [ int(reg.match(x).groups()[1]) for x in pool.get_list() if reg.match(x) and reg.match(x).groups()[1] ]
    if not result:
        result = [ 0 for x in pool.get_list() if reg.match(x) ]
    return result
    
def find_pool_by_metadata(pool,partition,prefix,**kwargs):
    reg = re.compile('(/%s/%s)([0-9]*).*' % (partition,prefix))
    keys=kwargs.keys()
    keys.sort()
    sortedvalues=[ kwargs[key] for key in keys ]
    return [ y for y,z in [ [x,pool.get_metadata([x])] for x in pool.get_list() if reg.match(x) ] if pool.get_metadata_value([y],[[z]])[0]==sortedvalues]

def create_pool(pool,nodeaddress,description,nodelist,addresslist,portlist,rdid,**kwargs):
    try:
        addrrdidlist = [address+'%'+rdid for address in addresslist]
        nodeaddress.create(nodelist,addrrdidlist,[0]*len(nodelist))
    except Exception, e:
        print e
    memberslist = [{ 'port': portlist[nodelist.index(x)], 'address': x } for x in nodelist ]
    keys=kwargs.keys()
    keys.sort()
    sortedvalues=[ kwargs[key] for key in keys ]
    try:
        pool.create_v2([description],['LB_METHOD_ROUND_ROBIN'],[memberslist])
    except Exception,e:
        print "Cannot create pool due to error: %s" % e
        sys.exit(3)
    monitorassoc =  {'monitor_templates':['/Common/generic_http_monitor'], 'type': 'MONITOR_RULE_TYPE_SINGLE', 'quorum': 0}
    try:
        pool.set_monitor_association([{'pool_name': description, 'monitor_rule': monitorassoc}])
    except Exception,e:
        print "Cannot enable pool monitoring due to error: %s" % e
    pool.add_metadata([description],[keys],[sortedvalues])

def add_member(pool,nodeaddress,description,nodelist,addresslist,portlist,rdid):
    try:
        addrrdidlist = [address+'%'+rdid for address in addresslist]
        nodeaddress.create(nodelist,addrrdidlist,[0]*len(nodelist))
    except Exception, e:
        print e
    memberslist = [{ 'port': portlist[nodelist.index(x)], 'address': x } for x in nodelist ]
    try:
        pool.add_member_v2([description], [memberslist])
    except Exception, e:
        print e
    
def pool_members_list(pool,description):
    return pool.get_member_v2([description])

# Rancher Metadata client
def get_current_metadata_entry(entry):
    headers = {
        'User-Agent': "selfpublish-rancher/0.1",
        'Accept': 'application/json'
    }
    req = urllib2.Request('http://rancher-metadata.rancher.internal/latest/%s' % entry, headers=headers)
    response = urllib2.urlopen(req).read()
    return json.loads(response.decode('utf8 '))
# API client

def get_current_api_entry(api_endpoint,access_key,secret_key,payload):
    headers = {
        'User-Agent': "selfpublish-rancher/0.1",
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'Basic '+base64.standard_b64encode(access_key + ':' + secret_key).encode('latin1').strip()
    }
    print "Accessing: %s" % api_endpoint
    request = urllib2.Request(api_endpoint,payload,headers)
    response = urllib2.urlopen(request).read()
    return json.loads(response.decode('utf8 '))

# functions returning data about services in other stacks needing publishing
# Returns whether the service should be published on this stack
def should_be_published_service(service,publish_label_prefix,stack):
    publish_label_stack = publish_label_prefix+'.lbstack'
    return 'labels' in service and publish_label_stack in service['labels'] and service['labels'][publish_label_stack] == stack

# Function returning hostid<->hostname correspondence
def get_host_hostid():
    return dict([ (int(x['hostId']),x['hostname']) for x in get_current_metadata_entry('hosts') ])

# functions returning data about the load balancer stack

def get_mystack_info():
    selfmetadata = get_current_metadata_entry('self')
    return { 'stack': selfmetadata['stack']['name'],'stack_uuid': selfmetadata['stack']['uuid'], 'env_uuid': selfmetadata['stack']['environment_uuid'] }


def get_current_environment(rancher_api_url,access_key,secret_key,my_dict):
    """ Get the environment object from the API
        From some unknown reason, we have different names for entities in Rancher metadata/Rancher UI/Rancher API
        -----------------------------------------
        |Rancher metadata|Rancher UI |Rancher API|
        ------------------------------------------
        |stack           |stack      |environment|
        |environment     |environment|project    |
        |service         |service    |service    |
    """
    proj_result = get_current_api_entry(rancher_api_url+'/projects/?uuid=%s' % my_dict['env_uuid'],access_key,secret_key,None)
    environments_link = proj_result['data'][0]['links']['environments']
    env_result = get_current_api_entry(environments_link+'/?uuid=%s' % my_dict['stack_uuid'],access_key,secret_key,None)
    return env_result

def get_current_lb_links(access_key,secret_key,env_result):
    payload = '{ }'
    full_config = get_current_api_entry(env_result['data'][0]['actions']['exportconfig'],access_key,secret_key,payload)
    dockercompose_dict = simpleyaml.load(full_config['dockerComposeConfig'])
    full_config = [ y for x,y in dockercompose_dict.iteritems() if y['image'].find('load-balancer-service') != -1 ]
    if len(full_config) == 1:
        return full_config[0]['links']
    else:
        raise Exception("dockercompose does not have the right format or no load balancer present in configuration!")
    
def get_load_balancer(access_key,secret_key,env_result):
    service_result = get_current_api_entry(env_result['data'][0]['links']['services'],access_key,secret_key,None)
    lbservice_link = [ x['links']['self'] for x in service_result['data'] if x['type'] == 'loadBalancerService' ]
    if len(lbservice_link) == 1:
        lbservice_result = get_current_api_entry(lbservice_link[0],access_key,secret_key,None)
    elif len(lbservice_link) > 1:
        raise Exception("Too many load balancers in stack!; Only one is supported")
    else:
        raise Exception("No load balancer found in stack!")
    return lbservice_result
        

def main():
    try:
        rancher_api_url=os.environ['CATTLE_URL']
        access_key=os.environ['CATTLE_ACCESS_KEY']
        secret_key=os.environ['CATTLE_SECRET_KEY']
### Awaiting Secrets Bridge integration....
### The bigip credentials will be retrieved from Vault if vault is enabled and from env variables otherwise
### We should add validations here
        bigip_address = os.environ['BIGIP_ADDRESS']
        bigip_user = os.environ['BIGIP_USERNAME']
        bigip_password = os.environ['BIGIP_PASSWORD']
        bigip_partition = os.environ['BIGIP_PARTITION']
        bigip_routedomain = os.environ['BIGIP_ROUTEDOMAIN']
        bigip_virtualserver = os.environ['BIGIP_VIRTUALSERVER']
        bigip_pool_prefix = os.environ['BIGIP_POOL_PREFIX']
        service_port = os.environ['CONTAINER_DEFAULT_PORT']
    except KeyError,e:
        print "At least one env variable is not set, for the moment the one missing is: %s; exiting..." % e
        time.sleep(30)
        sys.exit(3)
    logging.basicConfig(level=logging.INFO)
    b = bigsuds.BIGIP(
        hostname = bigip_address,
        username = bigip_user,
        password = bigip_password,
        )
    datagroupclass = b.LocalLB.Class
    pool = b.LocalLB.Pool
    nodeaddress = b.LocalLB.NodeAddressV2
    routedomain = b.Networking.RouteDomainV2
    #logging.getLogger('suds.client').setLevel(logging.DEBUG)

##  Rancher stuff
    myinfo_dict=get_mystack_info()
    mystack = myinfo_dict['stack']
    env = get_current_environment(rancher_api_url,access_key,secret_key,myinfo_dict)
    # Finding the link to the loadbalancer add service
    lb = get_load_balancer(access_key,secret_key,env)
    lb_addservice_link = lb['actions']['addservicelink']
    hostid2host = get_host_hostid()
    lb_public_endpoints = [ (x['ipAddress'],x['port'],hostid2host[int(x['hostId'])]) for x in lb['publicEndpoints'] ]
    (addresslist,portlist,nodelist) = map(list, zip(*lb_public_endpoints))

    # Finding services that needs to be published
    project = get_current_api_entry(rancher_api_url+'/projects/?uuid=%s' % myinfo_dict['env_uuid'],access_key,secret_key,None)
#    print json.dumps(project,sort_keys=True,indent=4, separators=(',', ': '))
    selected_services = [ (get_current_api_entry(project['data'][0]['links']['services']+'/?uuid='+service['uuid'],access_key,secret_key,None),service['name'],service['stack_name'])\
                           for service in get_current_metadata_entry('services') if should_be_published_service(service,'com.rancher.published',mystack) ]
    [ add_loadbalancer_entry(lb_addservice_link, service, access_key, secret_key) for service in selected_services ]

# If everything went smooth in Rancher LB let's move to BigIP

# Let's create the pool in BigIP
    b.System.Session.set_active_folder("/Common")
    try:
        rdid = get_rd_id(routedomain,bigip_routedomain)
    except Exception, e:
        print e
        sys.exit(3)
    description = bigip_pool_prefix+'_'+project['data'][0]['name'].replace(' ','_')+'_pool'
    b.System.Session.set_active_folder("/"+bigip_partition)
    if pool_exists(b,pool,description):
        member_list = pool_members_list(pool,description)[0]
# We presume that one node will never be included in the same pool with two TCP ports
        not_added_yet = set(nodelist) - set([ x['address'].split("/")[2] for x in member_list ])
        if not_added_yet:
            not_added_yet_index = [ nodelist.index(x) for x in not_added_yet ]
            addresslist = [ addresslist[x] for x in not_added_yet_index ]
            portlist = [ portlist[x] for x in not_added_yet_index ]
            nodelist = [ nodelist[x] for x in not_added_yet_index ]
            add_member(pool,nodeaddress,description,nodelist,addresslist,portlist,rdid)
    else:
        create_pool(pool,nodeaddress,description,nodelist,addresslist,portlist,rdid)
    # Look after datagroup list
    
    datagrouplist = find_datagroup_list(datagroupclass,bigip_partition,'ProxyPass%s' % bigip_virtualserver)    

    if not datagrouplist:
        print "Can't find datagroup list"
        sys.exit(3)
    memberdatavalue = [['%s.%s/ %s' % (service[1],service[2],description) for service in selected_services]]
    datagrouplist[0]['members'] = [ "/"+service[2]+'_'+service[1] for service in selected_services]
    
    edit_datagroup_list(datagroupclass,datagrouplist,memberdatavalue)

def add_loadbalancer_entry(lb_service_link, service, access_key, secret_key):
    payload={ 'serviceLink': {} }
    payload['serviceLink'].update({ 'serviceId': service[0]['data'][0]['id'], 'ports': [ '%s.%s=80' % (service[1],service[2]) ]})
    try:
        get_current_api_entry(lb_service_link,access_key,secret_key,json.dumps(payload))
    except urllib2.HTTPError, e:
        print "Encountered HTTP Error: %s" % e

if __name__ == "__main__":
    main()
