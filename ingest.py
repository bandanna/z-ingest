import requests
import json
from dotenv import load_dotenv
from os import environ
from ruamel import yaml
import sys
import datetime
import time
import ndjson
import boto3
import logging

# Config logging for both stdout and file
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    handlers=[logging.FileHandler('./data/z_api.log'),logging.StreamHandler()])
# Initiate logging object
logger=logging.getLogger()

class Config:
    """
    A class to handle all the necessary configurations that will be used to call the API, process the data, and write
    to S3.
    """


    def __init__(self,conf_path:str='./config/z_api.yaml'):
        """

        Constructor for Config. It uses ruaml libary to read the confirugations form the given Yaml file and updates
        the objects' attributes with this configurations.

        Additionally, this class reads environment parameters that includes secrets.

        :param conf_path: relative path to the configurations file. Otherwise by default './config/z_api.yaml'
        """

        logger.info(f"Initiating config from {conf_path}.")
        self.conf=yaml.safe_load(open(conf_path))

        # Secret is printed here on DEBUG mode. Carefully on exposing DEBUG logs publicly.
        logger.debug(f"The loaded configurations from Yaml:\n {self.conf}")
        self.__api_key=self._get_api_key()
        logger.debug(f"The API_KEY={self.__api_key}")

        self.headers=self.get_headers()
        self.url=self.conf["url"]
        self.read_batch_size=self.conf["metadata"]["read_batch_size"]
        self.retry_sla=self.conf["metadata"]["retry_sla"]
        self.retry_time_delta = self.conf["metadata"]["retry_time_delta"]
        self.s3_bucket=self.conf["metadata"]["s3_bucket"]
        self.s3_key=self.conf["metadata"]["s3_key"]
        self.save_data_locally=self.conf["metadata"]["save_data_locally"]
        self.events=self.conf["events"]

    def get_headers(self):
        """
        Get the headers to call the API.
        :return: Valid headers as dict.
        """
        return {
            'x-api-key': f'{self.__api_key}',
            'Content-Type': f'{self.conf["headers"]["Content-Type"]}'
        }

    def _get_api_key(self):
        """
        Private method that reads API_Key secret stored as an environment variable. The env variable is either by ./.env
        following the template in ./.env_template. Or, as a shell session environment variable.

        :return: API_KEY str
        """

        load_dotenv()
        return environ.get('API_KEY')

class APIReader:
    """
    A class that is designed to read from the API provided in the configurations, batch the data while handling different
    errors, and return a list of the fetched documents.
    """

    def __init__(self,name,conf:Config,day):
        """
        Constructor that initiates objects of APIReader.
        :param name: the name of the event type.
        :param conf: the configurations object
        :param day: the day to be precessed.
        """
        self.name=name
        self.conf=conf
        self.day=day


    def _post_call_api(self, payload: dict,retry_sla:int):
        """
        Local private function that performs POST calls to the API, and handle the responses. In case of success it returns
        the returned batch of data. In case of timeout 502, it retries again up to retry_sla times. In case of errors it
        aborts.
        :param payload: the body of the API call.
        :param retry_sla: how many times to retry in case of 502.
        :return:
        """

        response = requests.post(self.conf.url,data=json.dumps(payload),headers=self.conf.headers)
        response_list = json.loads(response.content.decode('utf8'))
        # retry_sla=self.conf.retry_sla
        flag = response.status_code

        # The recursive run stopping condition. This stops recursive calls in case of flag==502
        if(retry_sla<1):
            logger.error(f"After {retry_sla} trials, the API returned errors.")
            flag=404

        elif(flag==200):
            logger.debug("Succesfful API batch call.")
            return response_list

        # in case of timeout, which is the only error that requires retrying. Retry again.
        elif(flag==502):
            retry_sla=retry_sla-1
            logger.warning(f"API returns Gateway Timeout - ERROR 502. Updated retry_sla={retry_sla}. Trying again ...")

            # if provided in the configurations to sleep before every retrial.
            time.sleep(self.conf.retry_time_delta)

            # retry again by calling this function recursively with the updated retry_sla value
            return self._post_call_api(payload,retry_sla)

        # in case of 400, 403, 405, or 404 that is flagged in case of all retry_sla times have passed.
        else:
            logger.error(f"Received ERROR response from the API.")
            raise Exception(f'ERROR from the API. Error Code = {flag}. Error message: \n {response_list}')

        return response_list

    log_file = open('./data/batches.log', 'w')


    def get_event_by_day(self, event_name: str, day: str, starting_after: str = None, ending_before: str = None):
        """
        The main function of this class. It gets all the necessary configurations and returns a list of all the documents
        available for the given even, by the given date, using the given Config.

        The function iterates over the available batches recursively. It starts from batch zero, the very first one. And
        it keeps iterating until the provided batch is less than the desired read_batch_size provided in the configurations.
        The batch sizes have to be between 10 and 100, which is a requirement by the API. If the last batch call retrieves
        less than 10, the API can handle that too.

        :param event_name: the name of the event type
        :param day: the day to fetch the data for
        :param starting_after: in case of asking for a specific batch, the starting_after cursor.
        :param ending_before: in case of asking for a specific batch, the ending_before cursor.
        :return: list of JSONs.
        """

        logger.info(f"Getting events by day={day}")

        # Handle wrong batch input by the user.
        if(self.conf.read_batch_size<10 or self.conf.read_batch_size>100):
            logger.error(f"read_batch_size has to be betewen 10 and 100, including. It is set to {self.conf.read_batch_size}")
            raise ValueError("read_batch_size has to be betewen 10 and 100, including.")
        else:
            logger.info(f"Updating cursor | type = {event_name} | starting_after={starting_after} | ending_before={ending_before}")

            if(starting_after is not None and ending_before is not None):
                payload = {"created": f"{day}", "type": f"{event_name}", "limit": self.conf.read_batch_size,
                           "starting_after":f"{starting_after}","ending_before":f"{ending_before}"}

            # It handles the 2nd batch onward
            elif(starting_after is not None):
                payload = {"created": f"{day}", "type": f"{event_name}", "limit": self.conf.read_batch_size, "starting_after":f"{starting_after}"}

            # Handles batch zero, which is the first batch (cold start)
            else:
                payload = {"created": f"{day}", "type": f"{event_name}", "limit": self.conf.read_batch_size}

        data_batch_list = self._post_call_api(payload,self.conf.retry_sla)
        logger.info(f"A new batch processed. Length = {len(data_batch_list)}.")
        self.log_file.write(f'{event_name} | starting_after={starting_after} \n')

        # In case it's the last batch, return the whole batch.
        if(len(data_batch_list)<self.conf.read_batch_size):
            logger.info("Last batch being processed.")
            return data_batch_list
        else:
            last_doc=data_batch_list[len(data_batch_list)-1]
            starting_after=last_doc["id"]

            # in case there are more batches, return the current batch without the last item
            # plus the next batch, which is called recursively.
            return data_batch_list[:-1] + self.get_event_by_day(event_name,day,starting_after)


if __name__=='__main__':

    # Get the date arg or consider today's date. The date format it YYYY-MM-DD
    day = sys.argv[1] if len(sys.argv)>1  else datetime.date.today()
    logger.info(f"Starting the ingestion for date={day}")

    # Initiate Config object to be reused for all the event types
    conf = Config()
    logger.info(f"Event types to be ingested {conf.events}")

    s3 = boto3.client('s3')

    # Iterate over the provided event types, call the api and write data for each.
    for event in conf.events:
        logger.info(f"Starting to load '{event}' data for {day}.")
        reader = APIReader(name=event, conf=conf, day=day)

        # Get the returned documents for the iterated `event` as a list of json objects.
        docs_list=reader.get_event_by_day(event, day)
        logger.info(f"Writing partitioned '{event}' data for {day} to S3 in {conf.s3_bucket}/{conf.s3_key}.")

        # Write data locally in `./data/` folder in case configured so.
        if (conf.save_data_locally==True):
            logger.info("The data is written locally, in addition to S3.")
            f = open(f'./data/TYPE={event}-DATE_PARTITION={day}-{event}.json', 'w')
            for doc in docs_list:
                json.dump(doc, f)
                f.write('\n')

        # Serialize the object using Newline Delimited Json package.
        serializedListObject = ndjson.dumps(docs_list)

        # Put in s3 as JSON file (technically it is many jsons newline delimited)
        s3.put_object(Bucket=conf.s3_bucket, Key=f'{conf.s3_key}/TYPE={event}/DATE_PARTITION={day}/data-{len(docs_list)}.json', Body=serializedListObject)