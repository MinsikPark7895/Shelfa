import re

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'r') as f:
    content = f.read()

content = content.replace("flange_serial_write(modbus_fc06(ADDR_TORQUE_ENABLE, 1))", "flange_serial_write(list(modbus_fc06(ADDR_TORQUE_ENABLE, 1)))")
content = content.replace("flange_serial_write(modbus_fc06(ADDR_TORQUE_ENABLE, 0))", "flange_serial_write(list(modbus_fc06(ADDR_TORQUE_ENABLE, 0)))")
content = content.replace("flange_serial_write(modbus_fc06(ADDR_GOAL_POSITION, goal_position))", "flange_serial_write(list(modbus_fc06(ADDR_GOAL_POSITION, goal_position)))")

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'w') as f:
    f.write(content)
