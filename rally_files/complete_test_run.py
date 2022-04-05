import logging

from rally_openstack.task import scenario
from rally_openstack.task.scenarios.cinder.utils import CinderBasic
from rally_openstack.task.scenarios.glance.images import GlanceBasic
from rally_openstack.task.scenarios.keystone.basic import KeystoneBasic
from rally_openstack.task.scenarios.neutron.utils import NeutronScenario
from rally_openstack.task.scenarios.nova.utils import NovaScenario

from rally.task import types
from rally.task import validation

LOG = logging.getLogger(__name__)

@scenario.configure(name="ScenarioPlugin.complete_test_run")
class CompleteTestRun(KeystoneBasic, GlanceBasic, NeutronScenario, NovaScenario):

    STEP_CLEAR = 0
    STEP_USER = 1
    STEP_IMAGE = 2
    STEP_NETWORK = 3
    STEP_SUBNET = 4
    STEP_FLAVOR = 5
    STEP_SERVER = 6

    server = None
    flavor = None
    subnet = None
    network = None
    image = None
    user = None

    def run(self, container_format, image_location, disk_format,
            visibility="private", min_disk=0, min_ram=0, properties=None,
            network_create_args=None, subnet_create_args=None,
            force_delete=False,
            detailed=True, is_public=True, marker=None, limit=None, sort_key=None, sort_dir=None,
            **kwargs
            ):
        self.container_format = container_format
        self.image_location = image_location
        self.disk_format = disk_format
        self.visibility = visibility
        self.min_disk = min_disk
        self.min_ram = min_ram
        self.properties = properties
        self.network_create_args = network_create_args
        self.subnet_create_args = subnet_create_args
        self.force_delete = force_delete
        self.detailed = detailed
        self.is_public = is_public
        self.marker = marker
        self.limit = limit
        self.sort_key = sort_key
        self.sort_die = sort_dir
        self.kwargs = kwargs
        """create user -> create image -> create network -> start VM ->
        pause VM -> resume VM -> delete VM -> delete network -> delete image -> delete user
        Optional 'min_sleep' and 'max_sleep' parameters allow the scenario
        to simulate a pause between volume creation and deletion
        (of random duration from [min_sleep, max_sleep]).
        :param image: image to be used to boot an instance
        :param flavor: flavor to be used to boot an instance
        :param min_sleep: Minimum sleep time in seconds (non-negative)
        :param max_sleep: Maximum sleep time in seconds (non-negative)
        :param force_delete: True if force_delete should be used
        :param kwargs: Optional additional arguments for server creation
        """

        try:
            self.create_sequence()
        except Exception as e:
            self.clean_sequence()
            raise e
        self.delete_sequence()

    def create_sequence(self):
        self.step = self.STEP_CLEAR
        self.user = self.admin_keystone.create_user()
        self.step = self.step + 1
        self.image = self.glance.create_image(
            container_format=self.container_format,
            image_location=self.image_location,
            disk_format=self.disk_format,
            visibility=self.visibility,
            min_disk=self.min_disk,
            min_ram=self.min_ram,
            properties=self.properties)
        self.step = self.step + 1
        self.network = self._create_network(self.network_create_args or {})
        self.step = self.step + 1
        if not self.subnet_create_args:
            self.subnet_create_args = {}
        self.subnet = self._create_subnet(
                    self.network, self.subnet_create_args, start_cidr="10.0.0.0/24")
        self.step = self.step + 1
        self.flavor = self._create_flavor(ram=512, vcpus=1, disk=1)
        self.step = self.step + 1
        self.nics = list()
        self.nics.append({'net-id': self.network["network"]["id"]})
        self.server_kwargs = {'nics': self.nics}
        if 'forced_host' in self.kwargs:
            self.server_kwargs['availability_zone'] = f'nova:{self.kwargs["forced_host"]}'
        self.server = self._boot_server(self.image, self.flavor, **self.server_kwargs)
        self.step = self.step + 1
        self._pause_server(self.server)
        self._unpause_server(self.server)
        pass

    def clean_sequence(self):
        if self.step >= self.STEP_FLAVOR and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_SUBNET and self.flavor:
            self._delete_flavor(self.flavor)
        if self.step >= self.STEP_NETWORK and self.subnet:
            self._delete_subnet(self.subnet)
        if self.step >= self.STEP_IMAGE and self.network:
            self._delete_network(self.network["network"])
        if self.step >= self.STEP_USER and self.image:
            self.glance.delete_image(self.image.id)
        if self.user:
            self.admin_keystone.delete_user(self.user.id)

    def delete_sequence(self):
        if self.step >= self.STEP_SERVER:
            self._delete_server(self.server, force=self.force_delete)
            self.step = self.step - 1
        if self.step >= self.STEP_FLAVOR:
            self._delete_flavor(self.flavor)
            self.step = self.step - 1
        if self.step >= self.STEP_SUBNET:
            self._delete_subnet(self.subnet)
            self.step = self.step - 1
        if self.step >= self.STEP_NETWORK:
            self._delete_network(self.network["network"])
            self.step = self.step - 1
        if self.step >= self.STEP_IMAGE:
            self.glance.delete_image(self.image.id)
            self.step = self.step - 1
        if self.step >= self.STEP_USER:
            self.admin_keystone.delete_user(self.user.id)
            self.step = self.step - 1


@types.convert(image={"type": "glance_image"},
               flavor={"type": "nova_flavor"})
@validation.add("image_valid_on_flavor", flavor_param="flavor",
                image_param="image")
@validation.add("restricted_parameters",
                param_names="name",
                subdict="network_create_args")
@scenario.configure(name="ScenarioPlugin.CreateAndDeleteNetworkAndServer")
class CreateAndDeleteNetworkAndServer(KeystoneBasic, NeutronScenario, NovaScenario):
    STEP_CLEAR = 0
    STEP_NETWORK = 1
    STEP_SUBNET = 2
    STEP_SERVER = 3

    server = None
    subnet = None
    network = None

    def run(self, container_format, image, flavor, disk_format,
            visibility="private", min_disk=0, min_ram=0, properties=None,
            network_create_args=None, subnet_create_args=None,
            force_delete=False,
            detailed=True, is_public=True, marker=None, limit=None, sort_key=None, sort_dir=None,
            **kwargs
            ):
        self.container_format = container_format
        self.image = image
        self.flavor = flavor
        self.disk_format = disk_format
        self.visibility = visibility
        self.min_disk = min_disk
        self.min_ram = min_ram
        self.properties = properties
        self.network_create_args = network_create_args
        self.subnet_create_args = subnet_create_args
        self.force_delete = force_delete
        self.detailed = detailed
        self.is_public = is_public
        self.marker = marker
        self.limit = limit
        self.sort_key = sort_key
        self.sort_die = sort_dir
        self.kwargs = kwargs
        """create user -> create image -> create network -> start VM ->
        pause VM -> resume VM -> delete VM -> delete network -> delete image -> delete user
        Optional 'min_sleep' and 'max_sleep' parameters allow the scenario
        to simulate a pause between volume creation and deletion
        (of random duration from [min_sleep, max_sleep]).
        :param image: image to be used to boot an instance
        :param flavor: flavor to be used to boot an instance
        :param min_sleep: Minimum sleep time in seconds (non-negative)
        :param max_sleep: Maximum sleep time in seconds (non-negative)
        :param force_delete: True if force_delete should be used
        :param kwargs: Optional additional arguments for server creation
        """
        try:
            self.create_sequence()
        except Exception as e:
            self.clean_sequence()
            raise e
        self.delete_sequence()

    def create_sequence(self):
        self.step = self.STEP_CLEAR
        self.network = self._create_network((self.network_create_args or {}))
        self.step = self.step + 1
        if not self.subnet_create_args:
            self.subnet_create_args = {}
        self.subnet = self._create_subnet(
            self.network, self.subnet_create_args, start_cidr="10.0.0.0/24")
        self.step = self.step + 1
        self.nics = list()
        self.nics.append({'net-id': self.network["network"]["id"]})
        self.server_kwargs = {'nics': self.nics}
        if 'forced_host' in self.kwargs:
            self.server_kwargs['availability_zone'] = f'nova:{self.kwargs["forced_host"]}'
        self.server = self._boot_server(self.image, self.flavor, **self.server_kwargs)
        self.step = self.step + 1
        self._pause_server(self.server)
        self._unpause_server(self.server)
        self._delete_server(self.server, force=self.force_delete)
        self.step = self.step - 1
        self._delete_subnet(self.subnet)
        self.step = self.step - 1
        self._delete_network(self.network["network"])
        self.step = self.step - 1

    def clean_sequence(self):
        if self.step >= self.STEP_SUBNET and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_NETWORK and self.subnet:
            self._delete_subnet(self.subnet)
        if self.network:
            self._delete_network(self.network["network"])

    def delete_sequence(self):
        if self.step >= self.STEP_SERVER and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_SUBNET and self.subnet:
            self._delete_subnet(self.subnet)
        if self.step >= self.STEP_NETWORK and self.network:
            self._delete_network(self.network["network"])

@types.convert(image={"type": "glance_image"},
               flavor={"type": "nova_flavor"})
@validation.add("image_valid_on_flavor", flavor_param="flavor",
                image_param="image")
@validation.add("restricted_parameters",
                param_names="name",
                subdict="network_create_args")
@scenario.configure(name="ScenarioPlugin.NewDeploymentWorkload_old")
class NewDeploymentWorkload(KeystoneBasic, NeutronScenario, NovaScenario, CinderBasic):
    STEP_CLEAR = 0
    STEP_NETWORK = 1
    STEP_SUBNET = 2
    STEP_SERVER = 3

    server = None
    subnet = None
    network = None

    def run(self, container_format, image, flavor, disk_format,
            visibility="private", min_disk=0, min_ram=0, properties=None,
            network_create_args=None, subnet_create_args=None,
            force_delete=False,
            detailed=True, is_public=True, marker=None, limit=None, sort_key=None, sort_dir=None,
            **kwargs
            ):
        self.container_format = container_format
        self.image = image
        self.flavor = flavor
        self.disk_format = disk_format
        self.visibility = visibility
        self.min_disk = min_disk
        self.min_ram = min_ram
        self.properties = properties
        self.network_create_args = network_create_args
        self.subnet_create_args = subnet_create_args
        self.force_delete = force_delete
        self.detailed = detailed
        self.is_public = is_public
        self.marker = marker
        self.limit = limit
        self.sort_key = sort_key
        self.sort_die = sort_dir
        self.kwargs = kwargs
        """create user -> create image -> create network -> start VM ->
        pause VM -> resume VM -> delete VM -> delete network -> delete image -> delete user
        Optional 'min_sleep' and 'max_sleep' parameters allow the scenario
        to simulate a pause between volume creation and deletion
        (of random duration from [min_sleep, max_sleep]).
        :param image: image to be used to boot an instance
        :param flavor: flavor to be used to boot an instance
        :param min_sleep: Minimum sleep time in seconds (non-negative)
        :param max_sleep: Maximum sleep time in seconds (non-negative)
        :param force_delete: True if force_delete should be used
        :param kwargs: Optional additional arguments for server creation
        """
        try:
            self.init_params()
            self.create_sequence()
        except Exception as e:
            self.clean_sequence()
            raise e
        self.delete_sequence()

    def init_params(self):
        if not (self.network_create_args):
            self.network_create_args = {}
        if not self.router_create_args:
            self.router_create_args = None


    def create_sequence(self):
        self.step = self.STEP_CLEAR
        self.network = self._create_network((self.network_create_args or {}))
        self.step = self.step + 1
        if not self.subnet_create_args:
            self.subnet_create_args = {}

        self.subnet = self._create_subnet(
            self.network, self.subnet_create_args, start_cidr="10.0.0.0/24")
        self.router = self._create_router(self.router_create_args or {})
        self.port = self._create_port(network_id=self.network["id"])
        self.neutron.add_gateway_to_router(router_id=self.router["id"],
                                           network_id=self.network["id"],
                                           enable_snat=True)
        self.floating_ip = self._create_floatingip(
            floating_network=self.network)

        self.step = self.step + 1
        self.nics = list()
        self.nics.append({'net-id': self.network["network"]["id"]})
        self.server_kwargs = {'nics': self.nics}
        if 'forced_host' in self.kwargs:
            self.server_kwargs['availability_zone'] = f'nova:{self.kwargs["forced_host"]}'
        self.server = self._boot_server(self.image, self.flavor, **self.server_kwargs)
        self.step = self.step + 1

        create_volume_params = None or {}
        self.size = {'min': 1, 'max': 3}
        self.volume = self.cinder.create_volume(self.size, **create_volume_params)
        self.step = self.step + 1
        self._attach_volume(self.server, self.volume)
        self.step = self.step + 1
        self._detach_volume(self.server, self.volume)
        self.step = self.step - 1
        self.cinder.delete_volume(self.volume)
        self.step = self.step - 1


        router = self.neutron.create_router()
        self.neutron.add_gateway_to_router(
            router["id"], network_id=self.network["id"])
        self.neutron.add_interface_to_router(
            subnet_id=self.subnet["id"], router_id=router["id"])
        self.neutron.add_interface_to_router(
            subnet_id=self.subnet["id"], router_id=router["id"])
        self.floating_ip = self._create_floatingip(
            floating_network=self.network)
        self.neutron.associate_floatingip(
            floatingip_id=self.floating_ip["id"], port_id=self.port["id"])

        self._pause_server(self.server)
        self._unpause_server(self.server)
        self._delete_server(self.server, force=self.force_delete)
        self.step = self.step - 1
        self.neutron.dissociate_floatingip(floatingip_id=self.floating_ip["id"])
        self.neutron.remove_gateway_from_router(self.router["id"])
        self._delete_subnet(self.subnet)
        self.step = self.step - 1
        self._delete_network(self.network["network"])
        self.step = self.step - 1

    def clean_sequence(self):
        if self.step >= self.STEP_SUBNET and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_NETWORK and self.subnet:
            self._delete_subnet(self.subnet)
        if self.network:
            self._delete_network(self.network["network"])

    def delete_sequence(self):
        if self.step >= self.STEP_SERVER and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_SUBNET and self.subnet:
            self._delete_subnet(self.subnet)
        if self.step >= self.STEP_NETWORK and self.network:
            self._delete_network(self.network["network"])

@scenario.configure(name="ScenarioPlugin.NewDeploymentWorkload")
class NewDeploymentWorkload(KeystoneBasic, GlanceBasic, NeutronScenario, NovaScenario, CinderBasic):

    STEP_CLEAR = 0
    STEP_USER = 1
    STEP_IMAGE = 2
    STEP_NETWORK = 3
    STEP_SUBNET = 4
    STEP_FLAVOR = 5
    STEP_SERVER = 6

    server = None
    flavor = None
    subnet = None
    network = None
    image = None
    user = None

    def run(self, container_format, image_location, disk_format,
            visibility="private", min_disk=0, min_ram=0, properties=None,
            network_create_args=None, subnet_create_args=None,
            force_delete=False,
            detailed=True, is_public=True, marker=None, limit=None, sort_key=None, sort_dir=None,
            **kwargs
            ):
        self.container_format = container_format
        self.image_location = image_location
        self.disk_format = disk_format
        self.visibility = visibility
        self.min_disk = min_disk
        self.min_ram = min_ram
        self.properties = properties
        self.network_create_args = network_create_args
        self.subnet_create_args = subnet_create_args
        self.force_delete = force_delete
        self.detailed = detailed
        self.is_public = is_public
        self.marker = marker
        self.limit = limit
        self.sort_key = sort_key
        self.sort_die = sort_dir
        self.kwargs = kwargs
        """create user -> create image -> create network -> start VM ->
        pause VM -> resume VM -> delete VM -> delete network -> delete image -> delete user
        Optional 'min_sleep' and 'max_sleep' parameters allow the scenario
        to simulate a pause between volume creation and deletion
        (of random duration from [min_sleep, max_sleep]).
        :param image: image to be used to boot an instance
        :param flavor: flavor to be used to boot an instance
        :param min_sleep: Minimum sleep time in seconds (non-negative)
        :param max_sleep: Maximum sleep time in seconds (non-negative)
        :param force_delete: True if force_delete should be used
        :param kwargs: Optional additional arguments for server creation
        """
        try:
            self.init_params()
            self.create_sequence()
        except Exception as e:
            self.clean_sequence()
        self.delete_sequence()

    def init_params(self):
        if not (self.network_create_args):
            self.network_create_args = {}
            #self.network_create_args = {"router_external":True}
        if not hasattr(self, 'router_create_args'):
            self.router_create_args = {}
        if not hasattr(self, 'port_create_args'):
            self.port_create_args = {}


    def create_sequence(self):
        self.step = self.STEP_CLEAR
        self.user = self.admin_keystone.create_user()
        self.step = self.step + 1
        self.image = self.glance.create_image(
            container_format=self.container_format,
            image_location=self.image_location,
            disk_format=self.disk_format,
            visibility=self.visibility,
            min_disk=self.min_disk,
            min_ram=self.min_ram,
            properties=self.properties)
        self.step = self.step + 1
        self.network = self._create_network(self.network_create_args or {})
        self.network_ext = self.network['network']
        #self.network_ext = self.neutron.find_network("network_ext")
        self.step = self.step + 1
        if not self.subnet_create_args:
            self.subnet_create_args = {}
        self.subnet = self._create_subnet(
            self.network, self.subnet_create_args, start_cidr="10.0.0.0/24")
        if not self.port_create_args:
            self.port_create_args = {}
        self.router = self.neutron.create_router()
        #self.neutron.add_gateway_to_router(router_id=self.router['router']['id'],
        #                               network_id=self.network_ext['id'],
        #                               enable_snat=True)
        self.port = self.neutron.create_port(
            network_id=self.network_ext['id'], **self.port_create_args)
        #self.floating_ip = self.neutron.create_floatingip(self.network_ext)

        self.step = self.step + 1
        self.flavor = self._create_flavor(ram=512, vcpus=1, disk=1)
        self.step = self.step + 1
        self.nics = list()
        self.nics.append({'net-id': self.network_ext["id"]})
        self.server_kwargs = {'nics': self.nics}
        if 'forced_host' in self.kwargs:
            self.server_kwargs['availability_zone'] = f'nova:{self.kwargs["forced_host"]}'
        self.server = self._boot_server(self.image, self.flavor, **self.server_kwargs)

        security_group_create_args = {}
        security_group = self._create_security_group(
            **security_group_create_args)
        self._delete_security_group(security_group)

        keypair_args = {}
        keypair = self._create_keypair(**keypair_args)
        self._delete_keypair(keypair)
        self.step = self.step + 1

        create_volume_params = None or {}
        self.size = {'min': 1, 'max': 3}
        self.volume = self.cinder.create_volume(self.size, **create_volume_params)
        self.step = self.step + 1
        self._attach_volume(self.server, self.volume)
        self.step = self.step + 1
        self._detach_volume(self.server, self.volume)
        self.step = self.step - 1
        self.cinder.delete_volume(self.volume)
        self.step = self.step - 1

        self._pause_server(self.server)
        self._unpause_server(self.server)

        #self.neutron.delete_floatingip(self.floating_ip['id'])
        self.neutron.delete_port(self.port['id'])
        #self.neutron.remove_gateway_from_router(self.router['router']['id'])
        self.neutron.delete_router(self.router['id'])

        pass

    def clean_sequence(self):
        if self.step >= self.STEP_FLAVOR and self.server:
            self._delete_server(self.server, force=self.force_delete)
        if self.step >= self.STEP_SUBNET and self.flavor:
            self._delete_flavor(self.flavor)
        if self.step >= self.STEP_NETWORK and self.subnet:
            self._delete_subnet(self.subnet)
        if self.step >= self.STEP_IMAGE and self.network:
            self._delete_network(self.network["network"])
        if self.step >= self.STEP_USER and self.image:
            self.glance.delete_image(self.image.id)
        if self.user:
            self.admin_keystone.delete_user(self.user.id)

    def delete_sequence(self):
        if self.step >= self.STEP_SERVER:
            self._delete_server(self.server, force=self.force_delete)
            self.step = self.step - 1
        if self.step >= self.STEP_FLAVOR:
            self._delete_flavor(self.flavor)
            self.step = self.step - 1
        if self.step >= self.STEP_SUBNET:
            self._delete_subnet(self.subnet)
            self.step = self.step - 1
        if self.step >= self.STEP_NETWORK:
            self._delete_network(self.network["network"])
            self.step = self.step - 1
        if self.step >= self.STEP_IMAGE:
            self.glance.delete_image(self.image.id)
            self.step = self.step - 1
        if self.step >= self.STEP_USER:
            self.admin_keystone.delete_user(self.user.id)
            self.step = self.step - 1