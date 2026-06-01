from setuptools import find_packages, setup

package_name = 'shelfa_mqtt_bridge'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'paho-mqtt'],
    zip_safe=True,
    maintainer='Shelfa Team',
    maintainer_email='shelfa@example.com',
    description='MQTT Bridge for Shelfa Robot System',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'mqtt_bridge_node = shelfa_mqtt_bridge.mqtt_bridge_node:main'
        ],
    },
)
