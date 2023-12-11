from datetime import datetime
import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor

import bonfire.config as conf


log = logging.getLogger(__name__)


class AsyncElasticsearchHandler(logging.Handler):
    def __init__(self, es_url, metadata):
        super().__init__()
        self.es_url = es_url
        self.metadata = metadata
        self.executor = ThreadPoolExecutor(max_workers=10)

    def emit(self, record):
        self.metadata["time_of_logging"] = datetime.now().isoformat()
        self.metadata["duration"] = str(datetime.now() - datetime.fromisoformat(self.metadata["start_time"]))

        log_entry = {"log": self.format(record), "metadata": self.metadata}
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
