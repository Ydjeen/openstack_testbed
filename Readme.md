# Prepearing environment
* Access to nodes is defined in [multinode](deployer_files/multinode) file in `[all:vars]` section
* Potential cloud nodes need 2 network interfaces defined in [globals.yml](deployer_files/globals.yml). 
  *By default these are `enp2s0` as network interface and `eno1` as cluster interface

# Prepearing project folder
* Clone the repository

```
git clone git@github.com:Ydjeen/openstack_testbed.git
cd openstack_testbed
```
* Make sure pip and npm are installed.
* Prepare virtual environment and activate it

```
python3 -m venv ./venv
source ./activate
```
* Clone to a separate folder [openstack_anomaly_injection](https://github.com/Ydjeen/openstack_anomaly_injection) package

* Install it, by navigating to openstack_anomaly_injection/ folder, which includes setup.py file and executing
```
python setup.py install
```

* Go back to openstack_testbed project folder and install required pip packages

```
pip install -r requirements.txt
```
* Install elasticdump in project folder 

```
npm install elasticdump
```
* Create a node_list txt file in the root folder
* Specify machines in it, that are planned to be used for cloud deployments as a json, with an array "node_list" of objects with the following properties: "name", "domain_name", "ip". Example:


```
{
    "node_list" : [
        {
            "name" : "node0",
             "domain_name" : "node1.some_org.de",
             "ip" : "192.168.1.5"
        },
        {
            "name" : "node1",
             "domain_name" : "node2.some_org.de",
             "ip" : "192.168.1.6"
        }
   ]
}
```

* Set your ssh crenedtials to this nodes in deployer_files/multinode as ansible_user and ansible_private_key_file fields.

# Run flask application

* Using built-in functionality

```
FLASK_APP=app.py flask run -p 5001 --host=0.0.0.0
```
* Using gunicorn
```
gunicorn --log-file log --capture-output -w 1 app:app -b 0.0.0.0:5001 -t 4000 --daemon
```

* Access it via `127.0.0.1:5001`

#obsolete REST API description
* Deploy a new config using POST request on `/configs/` URL
  * Control node is specified as `control` parameter
  * Compute nodes are specified as `compute` parameter
  * Nodes are specified as 3 digit number
  * Example on how to request a deployment with 2 compute nodes

```
curl wally096.cit.tu-berlin.de:5001/configs/ -d control=096 -d compute=098 -d compute=099 -X POST -v
```
* Get list of all configs using GET request on `/configs/` URL
  * Example

```
curl wally096.cit.tu-berlin.de:5001/configs/ -X GET -v
```
* Request an openstack to be destroyed using DELETE request on `/configs/{config_id}/` URL
  * Replace {config_id} by id of configuration that has to be destroyed
  * Example

```
curl wally096.cit.tu-berlin.de:5001/configs/1/ -X DELETE -v
```

# Post deployment
* Everything that has to do with deployed cloud is located in `deploy_list/deployment{config_id}` folder

# Troubleshooting

* If a node does not have `eno1` interface a possible solution might be to use netplan:
  * Add eno1 interface to `/etc/netplan/01-netcfg.yaml` file

```
network:
  version: 2
  renderer: networkd
  ethernets:
    enp2s0:
      dhcp4: yes
    eno1:
      dhcp4: false
      addresses: [192.168.101.122/24]
```
  * Apply changes via `sudo netplan apply`
