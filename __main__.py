import opentherm
import code
import datetime
import logging
import signal
import json
import paho.mqtt.client as mqtt

# Values used to parse boolean values of incoming messages
true_values=('True', 'true', '1', 'y', 'yes')

# Default settings
settings = {
    "otgw" : {
        "type": "serial",
        "device": "/dev/ttyUSB0",
        "baudrate": 9600
    },
    "mqtt" : {
        "client_id": "otgw",
        "host": "127.0.0.1",
        "port": 1883,
        "keepalive": 60,
        "bind_address": "",
        "username": None,
        "password": None,
        "qos": 0,
        "pub_topic_namespace": "otgw/value",
        "sub_topic_namespace": "otgw/set",
        "retain": False
    }
}

# Update default settings from the settings file
with open('config.json') as f:
    settings.update(json.load(f))

# Set the namespace of the mqtt messages from the settings
opentherm.topic_namespace=settings['mqtt']['pub_topic_namespace']

# Set up logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def on_mqtt_connect(client, userdata, flags, rc):
    # Subscribe to all topics in our namespace when we're connected. Send out
    # a message telling we're online
    log.info("Connected with result code "+str(rc))
    mqtt_client.subscribe('{}/#'.format(settings['mqtt']['sub_topic_namespace']))
    mqtt_client.publish(
        topic=opentherm.topic_namespace,
        payload="online",
        qos=settings['mqtt']['qos'],
        retain=settings['mqtt']['retain'])

def on_mqtt_message(client, userdata, msg):
    # Handle incoming messages
    # MM added MM= (max_relative_modulation) and SH= (max_ch_water_setpoint) to list incoming messages
    log.debug("Received message on topic {} with payload {}".format(
                msg.topic, str(msg.payload)))
    command_generators={
        "otgw/set/max_relative_modulation_level": \
            lambda _ :"MM={:.0f}".format(float(_)),
        "otgw/set/max_ch_water_setpoint": \
            lambda _ :"SH={:.0f}".format(float(_)),
        "otgw/set/room_setpoint/temporary": \
            lambda _ :"TT={:.2f}".format(float(_)),
        "otgw/set/room_setpoint/constant":  \
            lambda _ :"TC={:.2f}".format(float(_)),
        "otgw/set/outside_temperature":     \
            lambda _ :"OT={:.2f}".format(float(_)),
        "otgw/set/hot_water/enable":        \
            lambda _ :"HW={}".format('1' if _ in true_values else '0'),
        "otgw/set/hot_water/temperature":   \
            lambda _ :"SW={:.2f}".format(float(_)),
        "otgw/set/central_heating/enable":  \
            lambda _ :"CH={}".format('1' if _ in true_values else '0'),
        # TODO: "otgw/set/raw/+": lambda _ :publish_to_otgw("PS", _)
    }
    # Find the correct command generator from the dict above
    command_generator = command_generators.get(msg.topic)
    if command_generator:
        # Get the command and send it to the OTGW
        command = command_generator(msg.payload)
        log.info("Sending command: '{}'".format(command))
        otgw_client.write("{}\r".format(command))


def on_otgw_message(message):
    # Send out messages to the MQTT broker
    log.debug("[{}] {}".format(str(datetime.datetime.now()), message))
    mqtt_client.publish(
        topic=message[0],
        payload=message[1],
        qos=settings['mqtt']['qos'],
        retain=settings['mqtt']['retain'])


log.info("Initializing MQTT")

# Set up paho-mqtt
mqtt_client = mqtt.Client(
    client_id=settings['mqtt']['client_id'])
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

if settings['mqtt']['username']:
    mqtt_client.username_pw_set(
        settings['mqtt']['username'],
        settings['mqtt']['password'])

# The will makes sure the device registers as offline when the connection
# is lost
mqtt_client.will_set(
    topic=opentherm.topic_namespace,
    payload="offline",
    qos=settings['mqtt']['qos'],
    retain=True)

# Let's not wait for the connection, as it may not succeed if we're not
# connected to the network or anything. Such is the beauty of MQTT
mqtt_client.connect_async(
    host=settings['mqtt']['host'],
    port=settings['mqtt']['port'],
    keepalive=settings['mqtt']['keepalive'],
    bind_address=settings['mqtt']['bind_address'])
mqtt_client.loop_start()

log.info("Initializing OTGW")

# Import the module for the correct gateway type and return a reference to
# the type itself, so we can instantiate it easily
otgw_type = {
    "serial" : lambda: __import__('opentherm_serial',
                              globals(), locals(), ['OTGWSerialClient'], 0) \
                              .OTGWSerialClient,
    "tcp" :    lambda: __import__('opentherm_tcp',
                              globals(), locals(), ['OTGWTcpClient'], 0) \
                              .OTGWTcpClient,
                                  # This is actually not implemented yet
}[settings['otgw']['type']]()

# Create the actual instance of the client
otgw_client = otgw_type(on_otgw_message, **settings['otgw'])

# Start the gateway client's worker thread
otgw_client.start()

log.info("Running")

# Block until the gateway client is stopped
otgw_client.join()

log.info("Done")
