# Rancher - BigIP integration


## Description

This small program tries to automate the setup of Rancher load balancers and BigIP load balancers based on service labels.

The following schema explains a bit the architecture:

![Architecture image](https://cdn.rawgit.com/brutus333/rancher-self-publish/master/global_lb.svg)

The program is meant to be called from the Rancher catalog since sensitive configuration options like BigIP username and password are taken from Rancher metadata service pushed via catalog integration.

## How it works

The program will look in the Rancher metadata after it's stack and will query the API for a load balancer service located in the same stack.

The docker-compose and rancher-compose files reflects this setup.

After it finds his own load balancer it will first check if the BigIP Pool definition exists and if has all nodes in the environments as members in the pool. If not, it will create/update the pool definition.

Next, it will check the list of services in other stacks having a default label of com.rancher.published=${stack_name} where stack_name is the name of the stack containing the load balancer and this program; for any service found it will update Rancher load balancer configuration and BigIP configuration to match the convention: context path ${stack_name}_${service_name} will point to service ${service_name} from stack ${stack_name}.

## Setup

After filling all required answers in the rancher catalog, the stack should start gracefully. It will complain if cannot connect to Rancher metadata, Rancher API or load balancer. In this cases, it will exit after 30s with error.
it should be enough time to see the error in the rancher UI logfile window.

## Limitations

Right now the code is beta quality - it needs some rewriting but it is useful as a pilot for bigip integration.


## TO DO

  - add labels for virtual server, pool suffix, partition and port
  - rewrite using classes
