from datetime import datetime as dt
import logging
import json
import requests
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import bonfire.config as conf


log = logging.getLogger(__name__)


class ElasticLogger():
    def __init__(self):
        self.es_telemetry = logging.getLogger("elasicsearch")
        metadata = {
            "uuid": str(uuid.uuid4()),
            "start_time": dt.now(),
            "bot": (conf.BONFIRE_BOT.lower() == 'true'),
            "command": self._mask_parameter_values(sys.argv[1:])
        }

        es_handler = next((h for h in self.es_telemetry.handlers
                           if type(h) is AsyncElasticsearchHandler), None)
        if es_handler:
            log.warning("AsyncElasticsearchHandler already configured for current logger")

        self.es_handler = AsyncElasticsearchHandler(conf.ELASTICSEARCH_HOST, metadata)
        self.es_telemetry.addHandler(self.es_handler)

    @staticmethod
    def _mask_parameter_values(cli_args):
        masked_list = []

        is_parameter = False
        for arg in cli_args:
            if is_parameter:
                masked_arg = f"{arg.split('=')[0]}=*******"
                masked_list.append(masked_arg)
                is_parameter = False
            else:
                masked_list.append(arg)
                is_parameter = arg == '-p' or arg == '--set-parameter'

        return masked_list

    def send_telemetry(self, log_message, success=True):
        self.es_handler.set_success_status(success)

        self.es_telemetry.info(log_message)


class AsyncElasticsearchHandler(logging.Handler):
    def __init__(self, es_url, metadata):
        super().__init__()
        self.es_url = es_url
        self.metadata = metadata
        self.executor = ThreadPoolExecutor(max_workers=10)

    def emit(self, record):
        self.metadata["@timestamp"] = dt.now().isoformat()
        self.metadata["elapsed_sec"] = (dt.now() - self.metadata["start_time"]).total_seconds()

        # copy and modify metadata for json formatting
        metadata = self.metadata
        metadata["start_time"] = metadata["start_time"].isoformat()

        log_entry = {"log": self.format(record), "metadata": metadata}
        if conf.ENABLE_TELEMETRY:
            self.executor.submit(self.send_to_es, json.dumps(log_entry))

    def set_success_status(self, run_status):
        self.metadata["succeeded"] = run_status

    def send_to_es(self, log_entry):
        # Convert log_entry to JSON and send to Elasticsearch
        try:
            headers = {"Authorization": conf.ELASTICSEARCH_APIKEY,
                       "Content-Type": "application/json"}

            response = requests.post(self.es_url, headers=headers, data=log_entry, timeout=0.1)
            response.raise_for_status()
        except Exception as e:
            # Handle exceptions (e.g., network issues, Elasticsearch down)
            log.error("Error sending data to elasticsearch: %s", e)
