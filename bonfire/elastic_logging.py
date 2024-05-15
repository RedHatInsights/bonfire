from datetime import datetime as dt
import logging
import json
import requests
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import bonfire.config as conf


log = logging.getLogger(__name__)


class ElasticLogger:
    def __init__(self):
        self.es_telemetry = logging.getLogger("elasicsearch")

        # prevent duplicate handlers
        self.es_handler = next(
            (h for h in self.es_telemetry.handlers if type(h) is AsyncElasticsearchHandler), None
        )
        if not self.es_handler:
            self.es_handler = AsyncElasticsearchHandler(
                f"{conf.ELASTICSEARCH_HOST}/{conf.ELASTICSEARCH_INDEX}/_doc/"
            )
            self.es_telemetry.addHandler(self.es_handler)

    def send_telemetry(self, log_message, success=True):
        self.es_handler.set_success_status(success)

        self.es_telemetry.info(log_message)


class AsyncElasticsearchHandler(logging.Handler):
    def __init__(self, es_url):
        super().__init__()
        self.es_url = es_url
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.start_time = dt.now()
        self.metadata = {
            "uuid": str(uuid.uuid4()),
            "start_time": self.start_time.isoformat(),
            "bot": conf.BONFIRE_BOT,
            "client_id": conf.CLIENT_ID,
            "command": self._mask_parameter_values(sys.argv[1:]),
        }

    def emit(self, record):
        self.metadata["@timestamp"] = dt.now().isoformat()
        self.metadata["elapsed_sec"] = (dt.now() - self.start_time).total_seconds()

        log_entry = {"log": self.format(record), "metadata": self.metadata}

        if conf.ENABLE_TELEMETRY:
            if not conf.ELASTICSEARCH_APIKEY or not conf.ELASTICSEARCH_HOST:
                log.error("Bonfire telemetry secret(s) not set")
                return

            self.executor.submit(self.send_to_es, json.dumps(log_entry))

    def set_success_status(self, run_status):
        self.metadata["succeeded"] = run_status

    def send_to_es(self, log_entry):
        # Convert log_entry to JSON and send to Elasticsearch
        log.info("Sending telemetry data...")

        try:
            headers = {
                "Authorization": conf.ELASTICSEARCH_APIKEY,
                "Content-Type": "application/json",
            }

            response = requests.post(self.es_url, headers=headers, data=log_entry, timeout=0.1)
            response.raise_for_status()
            log.info("Successfully sent telemetry data")
        except Exception as e:
            # Handle exceptions (e.g., network issues, Elasticsearch down)
            log.error("Error sending data to elasticsearch: %s", e)

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
                is_parameter = arg == "-p" or arg == "--set-parameter"

        return masked_list
