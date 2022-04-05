import threading

from app import db
from cloud_components.request_executor import RequestExecutor


class RequestScheduler:

    def __init__(self, config_id):
        self.deploy_id = config_id
        self.__executing__ = False
        self.__executing_lock__ = threading.Lock()
        self.__current_request_id__ = None
        self.request_counter = 0
        pass

    def start_executing(self):
        if not self.__executing__:
            self.__executing_lock__.acquire()
            self.__executing__ = True
            self.__executing_lock__.release()
            thread_destroy = threading.Thread(target=self.__start_executing__, args=[], daemon=True)
            thread_destroy.start()

    def get_queued_requests(self):
        return RequestExecutor.query.filter(RequestExecutor.request_end == None) \
            .filter(RequestExecutor.deploy_id == self.deploy_id) \
            .order_by(RequestExecutor.request_time) \
            .all()

    def remove_queued_requests(self, request_id):
        provided_request = RequestExecutor.query. \
            filter(RequestExecutor.deploy_id == self.deploy_id) \
            .filter(RequestExecutor.id == request_id).first()
        requests_to_delete = RequestExecutor.query. \
            filter(RequestExecutor.deploy_id == self.deploy_id) \
            .filter(RequestExecutor.request_time > provided_request.request_time).all()
        db.session.delete(provided_request)
        for request in requests_to_delete:
            db.session.delete(request)
        db.session.commit()

    def get_current_request(self):
        if (not self.__current_request_id__):
            return None
        return RequestExecutor.query \
            .filter(RequestExecutor.deploy_id == self.deploy_id) \
            .filter(RequestExecutor.id == self.__current_request_id__) \
            .first()

    def request_now(self, request_executor):
        thread = threading.Thread(target=request_executor.execute, args=[], daemon=True)
        thread.start()

    # All queued requests are executed till none are found
    def __start_executing__(self):
        current_request : RequestExecutor = RequestExecutor.query \
            .filter(RequestExecutor.deploy_id == self.deploy_id) \
            .filter(RequestExecutor.request_end == None) \
            .order_by(RequestExecutor.request_time) \
            .first()
        try:
            while current_request:
                self.__current_request_id__ = current_request.id
                current_request.execute()
                current_request = RequestExecutor.query \
                    .filter(RequestExecutor.deploy_id == self.deploy_id) \
                    .filter(RequestExecutor.request_end == None) \
                    .order_by(RequestExecutor.request_time) \
                    .first()
                self.__current_request_id__ = None
        finally:
            self.__current_request_id__ = None
        self.__executing_lock__.acquire()
        self.__executing__ = False
        self.__executing_lock__.release()
