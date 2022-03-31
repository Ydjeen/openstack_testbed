import logging
import threading

from app import db
from cloud_components.request_executor import RequestExecutor
from cloud_components.request_scheduler import RequestScheduler


class RequestManager:

    def __init__(self):
        self.__request_schedulers__ = {}
        self.__schedulers_lock__ = threading.Lock()
        pass

    def __get_request_scheduler__(self, config_id):
        self.__schedulers_lock__.acquire()
        scheduler = self.__request_schedulers__.get(config_id)
        if scheduler is None:
            logging.info(f'Request scheduler created for config {config_id}')
            scheduler = RequestScheduler(config_id)
            self.__request_schedulers__[config_id] = scheduler
        self.__schedulers_lock__.release()
        return scheduler

    def __remove_request_executor(self, config_id):
        self.__schedulers_lock__.acquire()
        self.__request_schedulers__.pop(config_id)
        logging.info(f'Request executor removed from list for config {config_id}')
        self.__schedulers_lock__.release()

    def request_action(self, request_executor):
        db.session.add(request_executor)
        db.session.commit()
        self.__get_request_scheduler__(request_executor.deploy_id).start_executing()

    def get_schedule(self, config_id):
        return self.__get_request_scheduler__(config_id).get_queued_requests()

    def get_current_request(self, config_id):
        return self.__get_request_scheduler__(config_id).get_current_request()

    def get_request(self, deploy_id, request_id):
        return RequestExecutor.query.\
            filter(RequestExecutor.deploy_id == deploy_id) \
            .filter(RequestExecutor.id == request_id).first()

    def cancel_request(self, config_id, request_id):
        return self.__get_request_scheduler__(config_id).remove_queued_requests(request_id)
