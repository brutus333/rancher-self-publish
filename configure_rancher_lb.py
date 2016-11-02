#!/usr/bin/env python
import os
import simpleyaml
import urllib2
import json
import base64


# Metadata client
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

def get_publishing_config(stack):
    return list(map(compose_config, filter(should_be_published_service, get_current_metadata_entry('services'))))

def compose_config(service,lbservice,lbport):
    return {
                lbservice:  {
                   'external_links': [ '%s/%s:%s' % (service['stack_name'],service['service_name'],service['service_name']) ],
                   'labels': [ 'io.rancher.loadbalancer.target.%s/%s: %s' % (service['stack_name'],service['service_name'],port) ]
                }
           }

# functions returning data about the load balancer stack

def get_current_uuids():
    selfmetadata = get_current_metadata_entry('self')
    return { 'stack_uuid': selfmetadata['stack']['uuid'], 'env_uuid': selfmetadata['stack']['environment_uuid'] }


def get_current_environment(rancher_api_url,access_key,secret_key,uuid_dict):
    """ Get the environment object from the API
        From some unknown reason, we have different names for entities in Rancher metadata/Rancher UI/Rancher API
        -----------------------------------------
        |Rancher metadata|Rancher UI |Rancher API|
        ------------------------------------------
        |stack           |stack      |environment|
        |environment     |environment|project    |
        |service         |service    |service    |
    """
    proj_result = get_current_api_entry(rancher_api_url+'/projects/?uuid=%s' % uuid_dict['env_uuid'],access_key,secret_key,None)
    environments_link = proj_result['data'][0]['links']['environments']
    env_result = get_current_api_entry(environments_link+'/?uuid=%s' % uuid_dict['stack_uuid'],access_key,secret_key,None)
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
    rancher_api_url=os.environ['CATTLE_URL']
    access_key=os.environ['CATTLE_ACCESS_KEY']
    secret_key=os.environ['CATTLE_SECRET_KEY']
    uuid_dict=get_current_uuids()
    env = get_current_environment(rancher_api_url,access_key,secret_key,uuid_dict)
    lb_addservice_link = get_load_balancer(access_key,secret_key,env)['actions']['addservicelink']




if __name__ == "__main__":
    main()

