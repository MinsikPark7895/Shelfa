import re

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'r') as f:
    content = f.read()

content = content.replace("flange_serial_write(modbus_fc03(ADDR_PRESENT_POSITION, 4))", "flange_serial_write(list(modbus_fc03(ADDR_PRESENT_POSITION, 4)))")
content = content.replace("flange_serial_write(modbus_fc03(ADDR_MOVING, 1))", "flange_serial_write(list(modbus_fc03(ADDR_MOVING, 1)))")

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'w') as f:
    f.write(content)
