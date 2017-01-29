
TIRAMOLA_DIR = "/home/kostis/git/tiramola/"

import sys
sys.path.append(TIRAMOLA_DIR)

from Configuration import ModelConf
from QDTModel import QDTModel
from Constants import *
import random
import math
from pprint import pprint

MAX_VMS = 20
MIN_VMS = 1

def get_next_measurements(old_measurements, action, time):
    action_type, action_value = action
    load = get_load(time)
    num_vms = old_measurements[NUMBER_OF_VMS]
    if action_type == ADD_VMS:
        num_vms += action_value
    if action_type == REMOVE_VMS:
        num_vms -= action_value
    if num_vms > MAX_VMS:
        num_vms = MAX_VMS
    if num_vms < MIN_VMS:
        num_vms = MIN_VMS
    return { NUMBER_OF_VMS: num_vms, TOTAL_LOAD: load }

def get_load(time):
    return 75.0 + 45.0 * math.sin(2 * math.pi * time / 1000.0)

def get_reward(measurements, action, time):
    load = get_load(time)
    vms = measurements[NUMBER_OF_VMS]
    return min(10 * vms, load) - 7 * vms


CONFIGURATION_FILE = TIRAMOLA_DIR + "examples/qdt_2d_test/dt.json"

conf = ModelConf(CONFIGURATION_FILE)
assert conf.get_model_type() == Q_DT, "Wrong model type in Q-DT example"
model = QDTModel(conf.get_model_conf())

training_steps = 20000
print_steps    = 2000
max_steps      = training_steps + print_steps
epsilon        = 0.4

time = 0
measurements = { NUMBER_OF_VMS: 1, TOTAL_LOAD: get_load(0) }
model.set_state(measurements)
model.set_allow_splitting(False)

while time < max_steps:
    
    time += 1

    if random.uniform(0, 1) < epsilon and time < training_steps:
        action = random.choice(model.get_legal_actions())
    else:
        action = model.suggest_action()

    measurements = get_next_measurements(measurements, action, time)
    reward = get_reward(measurements, action, time)
    model.update(action, measurements, reward)

    if time >= training_steps:
        print(measurements[TOTAL_LOAD], 10 * measurements[NUMBER_OF_VMS])

#model.print_model(True)
#print model.get_percent_not_taken()


