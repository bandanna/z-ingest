# z-ingest

**Note**: This work have been annonymized. Apologies if some links/words/parameters don't make much sense. The abstract is right though. 

1. [Overview](#overview)

    1.1 [Requirements](#requirements)

    1.2 [Structure](#structure)

    1.3 [Configurations](#configurations)

    1.4 [How to?](#how-to)

    1.5 [Logging](#logging)

    1.6 [Scheduling](#scheduling)

2. [Assumptions](#assumptions)

3. [Deployment](#deployment)

4. [Potential Improvements](#potential-improvements-todos)

## Overview

This document discusses the implementation, design, setup, and other aspects regarding [the task](https://gist.github.com/androideva/1709370). 
The approach in mind was reaching a good working solution (not necessarily the most performant), readable, handling errors, and extensible (at least conceptually). 

If you are in a hurry to get started, I'd jump to this ["Cheatsheet"](#how-to). Otherwise, let's break things down!

<br>

### Requirements

- `python3`: the project was developed using `python3.7.5`
- The following Python modules (other versions can be compatible too). 
    ```
    - boto3==1.9.63
    - ruamel.yaml==0.16.10
    - ndjson==0.3.1
    - python-dotenv==0.13.0
    - requests==2.22.0
    ```
<br>

### Structure

The file handling the main functionality is `ingest.py`. This is a Python3-valid script written in OOP-ish way. It is executable (check [How to](#how-to)), has a `Main` and 2 classes. I hope I have managed to keep the code well-documented, but briefly about the classes:

(Terminology: I used the term _event_ in the code referring to type, as in `type=[balance_transaction, charge, customer, dispute, event, refund]` )

1. `Config`: this class handles the configurations provided in the `config/z_api.yaml` file as well as the environemnt variables. It initiates the Headers and acts as an enum to be used in the _Main_ as well as _APIReader_ class. The idea is as simple as creating a reusable structure for configurations, arguments, and parameters.
2. `APIReader`: This class uses the provided Config object, `event`, and `day`. It fetches the data from the API for that day, while handling different possible connection errors. Then it returns a list of JSONs to be serialized and dumped to S3. Dumping the files to S3 is handled by the Main. Consider each object of APIReader as a serparate event type, that should be read given certain configurations. For this project, it's the same Config object for all the events. 

The _tree_ below describes the files structure. I'll touch each one of the files separately:

```
.
├── README.md
├── .env (.gitignore-d)
├── .env_template
├── config
│   └── z_api.yaml
├── data (.gitignore-d)
│   ├── *.log
│   └── *.json
└── ingest.py
```

- `ingest.py`: described [above](#structure) in this section.
- `README.md`: this file.
- `config/`: the folder hosting the Yaml configuration files. Right now it includes one configuration file, yet it's an idea for that could be extended.
-  `/config/z_api.yaml`: the configurations file. Currently, the dynamic path is hardcoded inside `ingest.py`. I'll explain the different parameters in [Configurations](#Configurations). Surely, it could be passed as an argument if necessary.
- `.env_template`: this file shows the template for `.env` file. 
- `.env`: this file is not git-tracked. It includes the the API_KEY. The way to setup the API key is either:
    1. `API_KEY=<insert-your-api-key>` in `.env`.
    2. `export API_KEY=<insert-your-api-key>` as environment variable.
- `data/`: this folder is not git-tracked neither. If you chose in the [Configurations](#Configurations) to write the files locally, the files will be stored here. Additionally, the local `*.log` will be saved here.

<br>

### Configurations

Referring to the configurations in `/config/z_api.yaml`. Please, assume that all parameters are mandatory. Currently, there is no validation check for the inputs given in this configurations file. Surely, this could be improved and I added some ideas to [improvements/TODOs](#potential-improvements-todos).

-  _version_: the version of this configurations. 
- _url_: The API url to be (POST) called.
- _headers_: Any necessary headers except for the `x-api-key`. Example:

```
headers: 
  Content-Type: application/json
```

- _metadata_: it is a Yaml parent item that includes the following \<key-value> pairs.
    - _read_batch_size_: it reflects the "limit" parameter in the API. How many documents to read per call?
    - _s3_bucket_: the name of the bucket.
    - _s3_key_: the key path where the data is store.
    - _retry_sla_: in case of timeout 502 errors, how many times to retry?
    - _retry_time_delta_: how long in seconds to wait before retrying again.
    - _save_data_locally_: True/False, about saving the final ND-JSONs in `data/`
- _events_: a list of the events/types to fetched from the API. Example:
```
events:
  - balance_transaction
  - dispute
```
<br>

### How to
1. Clone this repository, or `unbundle` it. To avoid possible permission errors, please make sure to create a blank folder `./data`, as the script might not have permissions to do that.
2. Make sure you have the [requirements](#Requirements) set. 
3. Create `.env` as shown in `.env_template`. Make sure you keep this file .gitignore-d. Alternatively, you can set an environment variable `export API_KEY=<insert-your-api-key>`.
4. Check if the cloned configurations follow what you need, or adjust following [Configurations](#Configurations).
5. Run `ingest.py` using Python3. You may provide the day to be processed as an input following the structure `YYYY-MM-DD`, otherwise it'll take "today". As of `python3 ingest.py`
6. You can review the data in S3, or locally if you chose to store it locally too. Check the logs files too.

<br>

### Logging
The project uses `logging` Python module to write logs. The logs are streamed to stdout and written to the files in `data/*.log`, simultaneously. The default logging level is INFO, and as for now logging_level is not part of the Configurations and neither taken as an argument. This is a mentioned potential improvement in the [TODO](#potential-improvements-todos) list below. 

The majority of the logs are informative and appear as INFO. Yet, I have set Warning logs when retrying the API call due to 502 errors. And, I have set ERROR logs on Exceptions and Errors. Lastly, There are some DEBUG-leveled logs too. This type of logs may print sensitive secrets. 

The logs in `data/*.log` are 2 types:
- a copy of the stdout logs.
- logs the print the events and batches, in case this could help necessary debugging.

<br>

### Scheduling

The script `ingest.py` is scheduled to run using Crontab everyday at 7AM UTC. You can check in the EC2 machine `crontab -l` or edit using `crontab -e` (vim-like editor).

The current config is:
```
0 7 * * * python3 /home/ec2-user/z-ingest/ingest.py >/dev/null 2>&1
```

In [Deployment Proposals](#deployment-proposals) I discuss different ideas for scheduling this script. Yet, here I took a simple, but working, approach.

<br>


## Deployment

This section is divided into 2, the first refers to how it is currently deployed and the second discusses some deployment alternatives.

### Current Deployment

This project was deployed as follow:
- I was provided with access to an EC2 instance.
- I created a repository on github, then created ssh-key on the EC2 machine and granted it with read-only permissions to a single repository. In Github this appears as _DeployKey_ inside the settings of the repository itself.
- The secrets are provided as environment variables which I set manually following the instructions in the sections above.
- The missing Python libraries were also installed manually.
- Everytime I pushed something to Master branch, I accessed the EC2 machine through SSH, and git pulled the changes manually.
- The daily schedule is running as a cron job using Crontab.

### Deployment Proposals
 
 As many of the processes were done manually, it all could be automated. Again, there are two ways to look at it as described in the sub-sections below.

#### Tech Stack to run a similar solution as of now (Python script running on EC2):
 - Git service (i.e. github, gitlab, etc) 
 - Terraform
 - Ansible
 - CI/CD tool (i.e. Drone CI, Travis, etc)


 Flow:
 1. Terraform code is ready to provision the EC2 Machine. 
 2. Once the PR is available, `terraform plan` runs.
 3. When the PR is approved and merged. `terraform apply` deploys the instance.
 4. The python script could be part of the same terraform git repository or another one. Generally, I like to separate repositories for infrastructure from applications. But there are no rules here.
    
    4.a. If the Python script is part of the Terraform repository, then terraform can do the deployment. Preferably, terraform calls Ansible to install the dependencies and place the script in the right path. Ansible can set the cron job too. In this case, Ansible will be updating any changes to the Python script. 
    
    4.b. If the Python script is not part of the terraform repository. Then a CI would be triggered on new merges to Master branch. The CI will connect to the EC2 machine and do the required changes. Example, Drone CI could use a Docker with AWS Cli dependency and access then use AWS SSM API to execute commands remotely (it's possible to execute commands remotely using ssh too). The remote command can just git pull, or move necessary files/data if required.
5. The script and crontab will be updated in the EC2 instance.


#### Tech Stack to run another proposed solution
 - Git service (i.e. github, gitlab, etc) 
 - Terraform
 - Ansible
 - CI/CD tool (i.e. Drone CI, Travis, etc)
 - Apache Airflow
 - Optional: Containers Engine, preferably Kubernetes or Docker.

Flow:
 1. Terraform provisions Apache Airflow cluster (assuming it runs on EC2, ECS, or ASG). If we opt at preparing AMIs with all the necessary dependencies, then Packer could help here too. The AMI arn/id will be used in Terraform.
 2. Ansible does the installations and manages packages. (if needed)
 3. This project is in a different git repo than the Terraform one. It could actually be part of the repository where Airflow DAGs are stored if we used PythonOperator, or it could be in a separate repository if we dockerize it. Let's assume that it is in a separate respository. This leaves us with 3 repositories: 1. _Terraform_ (all infra work), 2. _airflow-dags_ (all airflow dags), 3. _z-ingest_ (this python project only).
 4. Assume we use KubernetesPodOperator:
    
    4.1. Once new changes are merged into Master of z-ingest repo, the CI builds a new image and pushes it to ECR (or any Docker repository). The images is tagged with something the Airflow DAG undestands. Say `tag=prod` (not `latest`). The image is simple able to run this project in a Docker.
    
    4.2. Either K8S or the Airflow DAG is configured on `always_pull=True` to enable checking and pulling images always before running.

    4.3. The Airflow DAG will run N Operators in parallel. Each for a different event type. The flow can be like ` upstream_task >> [KubernetesPodEventType1, KubernetesPodEventType2, KubernetesPodEventType3,..N] >> downstream_task`. Note: currently `ingest.py` loops over all the given event types in the configuration files. The proposed solution here requires being able to give one event at at time as an argument/input.

    4.4. This way Airflow coordinates the run of N Kubernetes pods known to it by name, parameters, and `tag=prod`. If there is a need to change anything from Airflow side, it can be done on airflow-dags repository. Surely, there can be a CI there to push any changes in Master to the Airflow cluster (i.e. $AIRFLOW_HOME/dags unless configured differently)

5. The ingestion logs are written to S3 from the app side. Airflow logs are written to Airflow logs destination. And the pods logs can be pulled using `FluentD` which is a daemon on K8S to send K8S logs to Cloudwatch.


<br>


## Assumptions
- Assuming the only non-documented error in Swagger that required retrial of API calls is “502 - gateway timeout”, other errors are critical and require aborting.
- The retreived newline delimited JSONs are valid for the downstream tasks. Whether it's loaded into Spectrum, Athena, or Spark, it'll be used as-is. The current solution does not handle cases like _flattening_ JSONs, or validating the data itself.
- Despite the fact it’s mocked data, I took concepts like security into account, and passed the x-api-key in `.env`.
- The script takes “today” date or expects a date provided by the user. I assume the user will provide a valid date structure of YYYY-MM-DD. There is no input validation.
- The user will insert valid configurations in `z_api.yaml`, there is no validation check there.
- I tested the following scenaraio. What if the the last iterative call have a valid batch size ("limit" between 10 and 100), but the available documents are invalid size (less than 10), the API will return what’s remaining, so no need to validate that from the application side neither.

<br>

## Potential improvements: TODOs
- It is possible to do threading. Due to the low number of events the scripts iterates sequentially over the list of provided event types. But it’s possible to run threads in parallel. This is limited to the multi-conn max option in the api itself. I am not sure how many parallel connections the API can handle, yet I received many 502s during the tests.
- The solution is designed from scratch to work with this API. Due to time limitation and trying to keep the solution simple, the script and configuration file are designed to work with this particular API mainly and not a generic solution to suit APIs with different structures (i.e. different curosr, date time format,). This point could be extended and improved.
- Possible to coordinate the code with external scheduling tools like Airflow, where it can run as processes in parallel. In other words, if we have N event types, we could run N Airflow Operators in parallel to call the API (assuming the API can handle multi-connection), the operators could be anything I.e. PythonOperator, PythonVirtualenvOperator, KubernetesPodOperator, DockerOperator, etc.
- Better ERROR catching and Exception handling.
- Introduce tests (unittests, integration tests, etc).
- Introduce Backfilling options: right now the focus is on day-to-day processes.
- Get the following parameters from config:
    - write_batch_size: in case the written batches should be split into different size (now it’s one file with all the loaded data). Similar to `coalesce(n:int)` in Spark.
    - logging_level: get INFO/Warning/Error logging level as an argument
    - logging_path: get the local logging path directory as.
- Save logs to S3.
- Implement JSON documents **flattening**. Right now the documents have depth of 1 or 2 levels at most. In case the data is loaded as structured data (e.g. RDBMS), it's possible to handle the embded documents using Json Path (or similar idea), or flatten it. 
