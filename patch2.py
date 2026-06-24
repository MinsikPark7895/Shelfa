import re

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'r') as f:
    content = f.read()

content = content.replace("struct.unpack('>H', str(header[4:6]))[0]", "struct.unpack('>H', header[4:6])[0]")
content = content.replace("struct.unpack('>H', str(header[6:8]))[0]", "struct.unpack('>H', header[6:8])[0]")
content = content.replace("struct.unpack('>H', str(payload[0:2]))[0]", "struct.unpack('>H', payload[0:2])[0]")
content = content.replace("struct.unpack('>I', str(payload[0:4]))[0]", "struct.unpack('>I', payload[0:4])[0]")
content = content.replace("struct.unpack('>i', str(payload[0:4]))[0]", "struct.unpack('>i', payload[0:4])[0]")
content = content.replace("struct.unpack('>h', str(current_reg))[0]", "struct.unpack('>h', current_reg)[0]")

with open('/home/user/Shelfa/ros2_ws/src/Doosan-E0509-ROBOTIS-RH-P12-RN-TCP-Bridge/dsr_gripper_tcp/dsr_gripper_tcp/gripper_tcp_bridge.py', 'w') as f:
    f.write(content)
