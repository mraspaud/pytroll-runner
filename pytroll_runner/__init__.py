"""Generic runner.

Example config file:

publisher_config:
  expected_files: /tmp/pytest-of-a001673/pytest-169/test_fake_publisher0/file?.bla
  output_files_log_regex: "Written output file : (.*.nc)"
  publisher_settings:
    nameservers: false
    port: 1979
  static_metadata:
    sensor: thermometer
  topic: /hi/there
script: /tmp/pytest-of-a001673/pytest-169/test_fake_publisher0/myscript_bla.sh
subscriber_config:
  addresses:
  - ipc://bla
  nameserver: false


"""
import argparse
import os
import re
from contextlib import closing
from glob import glob
from subprocess import PIPE, Popen

import yaml
from posttroll.message import Message
from posttroll.publisher import create_publisher_from_dict_config
from posttroll.subscriber import create_subscriber_from_dict_config


def main(args=None):
    """Main script."""
    parsed_args = parse_args(args=args)
    return run_and_publish(parsed_args.config_file)


def parse_args(args=None):
    """Parse commandline arguments."""
    parser = argparse.ArgumentParser("Pytroll Runner",
                                     description="Automate third party software in a pytroll environment")
    parser.add_argument("config_file",
                        help="The configuration file to run on.")
    return parser.parse_args(args)


def run_and_publish(config_file):
    """Run the command and publish the expected files."""
    command_to_call, subscriber_config, publisher_config = read_config(config_file)
    preexisting_files = check_existing_files(publisher_config)

    with closing(create_publisher_from_dict_config(publisher_config["publisher_settings"])) as pub:
        for log_output, mda in run_from_new_subscriber(command_to_call, subscriber_config):
            try:
                message = generate_message_from_log_output(publisher_config, mda, log_output)
            except KeyError:
                message = generate_message_from_expected_files(publisher_config, mda, preexisting_files)
                preexisting_files = check_existing_files(publisher_config)
            pub.send(message)


def generate_message_from_log_output(publisher_config, mda, log_output):
    """Generate message for the filenames present in the log output."""
    new_files = re.findall(publisher_config["output_files_log_regex"], str(log_output))
    message = generate_message_from_new_files(publisher_config, new_files, mda)
    return message


def check_existing_files(publisher_config):
    """Check for previously generated files."""
    filepattern = publisher_config["expected_files"]
    return set(glob(filepattern))


def read_config(config_file):
    """Read the configuration file."""
    with open(config_file) as fd:
        config = yaml.safe_load(fd.read())
    return config["script"], config["subscriber_config"], config["publisher_config"]


def run_from_new_subscriber(command, subscriber_settings):
    """Run the command with files gotten from a new subscriber."""
    with closing(create_subscriber_from_dict_config(subscriber_settings)) as sub:
        return run_on_messages(command, sub.recv())


def run_on_messages(command, messages):
    """Run the command on files from messages."""
    accepted_message_types = ["file", "dataset"]
    for message in messages:
        if message.type not in accepted_message_types:
            continue
        try:  # file
            files = [message.data["uri"]]
        except KeyError:  # dataset
            files = []
            files.extend(info["uri"] for info in message.data["dataset"])
        yield run_on_files(command, files), message.data


def run_on_files(command, files):
    """Run the command of files."""
    if not files:
        return
    process = Popen([os.fspath(command), *files], stdout=PIPE)
    out, _ = process.communicate()
    return out


def generate_message_from_expected_files(pub_config, extra_metadata=None, preexisting_files=None):
    """Generate a message containing the expected files."""
    new_files = find_new_files(pub_config, preexisting_files or set())

    return generate_message_from_new_files(pub_config, new_files, extra_metadata)


def generate_message_from_new_files(pub_config, new_files, extra_metadata):
    """Generate a message containing the new files."""
    metadata = populate_metadata(extra_metadata, pub_config.get("static_metadata", {}))
    dataset = []
    for filepath in sorted(new_files):
        filename = os.path.basename(filepath)
        dataset.append(dict(uid=filename, uri=filepath))
    if len(new_files) == 1:
        metadata.update(dataset[0])
        message_type = "file"
    else:
        metadata["dataset"] = dataset
        message_type = "dataset"
    return Message(pub_config["topic"], message_type, metadata)


def find_new_files(pub_config, preexisting_files):
    """Find new files matching the file pattern."""
    return check_existing_files(pub_config) - preexisting_files


def populate_metadata(extra_metadata, static_metadata):
    """Populate the metadata."""
    metadata = {}
    if extra_metadata is not None:
        metadata.update(extra_metadata)
        metadata.pop("uri", None)
        metadata.pop("uid", None)
        metadata.pop("dataset", None)
    metadata.update(static_metadata)
    return metadata
