#!/usr/bin/env python3
"""controller_manager spawner 대체용 간단 controller loader.

현재 환경의 controller_manager spawner가 RcutilsLogger.info 호환성 문제로 죽어서
joint_state_broadcaster가 올라오지 않는 경우가 있다. 이 노드는 같은 일을 서비스
호출로 직접 수행한다.
"""

import time

import rclpy
from controller_manager_msgs.srv import (
    ConfigureController,
    ListControllers,
    LoadController,
    SwitchController,
)
from rclpy.node import Node


DEFAULT_CONTROLLERS = ["joint_state_broadcaster", "dsr_controller2"]


class ControllerLoader(Node):
    def __init__(self):
        super().__init__("controller_loader")
        self.declare_parameter("controller_manager", "/dsr01/controller_manager")
        self.declare_parameter("controllers", DEFAULT_CONTROLLERS)
        self.declare_parameter("startup_delay_sec", 3.0)
        self.declare_parameter("service_timeout_sec", 20.0)

        self.controller_manager = str(self.get_parameter("controller_manager").value).rstrip("/")
        self.controllers = [str(item) for item in self.get_parameter("controllers").value]
        self.startup_delay_sec = float(self.get_parameter("startup_delay_sec").value)
        self.service_timeout_sec = float(self.get_parameter("service_timeout_sec").value)

        self.list_client = self.create_client(
            ListControllers,
            f"{self.controller_manager}/list_controllers",
        )
        self.load_client = self.create_client(
            LoadController,
            f"{self.controller_manager}/load_controller",
        )
        self.configure_client = self.create_client(
            ConfigureController,
            f"{self.controller_manager}/configure_controller",
        )
        self.switch_client = self.create_client(
            SwitchController,
            f"{self.controller_manager}/switch_controller",
        )

    def run(self):
        if self.startup_delay_sec > 0.0:
            print(f"[ControllerLoader] wait {self.startup_delay_sec:.1f}s before loading controllers")
            time.sleep(self.startup_delay_sec)

        for client in (
            self.list_client,
            self.load_client,
            self.configure_client,
            self.switch_client,
        ):
            if not client.wait_for_service(timeout_sec=self.service_timeout_sec):
                raise RuntimeError(f"service not available: {client.srv_name}")

        states = self.list_controllers()
        for name in self.controllers:
            state = states.get(name)
            if state is None:
                self.load_controller(name)
                states = self.list_controllers()
                state = states.get(name)

            if state not in ("inactive", "active"):
                self.configure_controller(name)

        states = self.list_controllers()
        inactive = [name for name in self.controllers if states.get(name) != "active"]
        if inactive:
            self.activate_controllers(inactive)

        states = self.list_controllers()
        print(f"[ControllerLoader] controller states: {states}")

    def list_controllers(self):
        response = self.call_service(self.list_client, ListControllers.Request())
        return {controller.name: controller.state for controller in response.controller}

    def load_controller(self, name):
        print(f"[ControllerLoader] load {name}")
        request = LoadController.Request()
        request.name = name
        response = self.call_service(self.load_client, request)
        if not response.ok:
            raise RuntimeError(f"load_controller failed: {name}")

    def configure_controller(self, name):
        print(f"[ControllerLoader] configure {name}")
        request = ConfigureController.Request()
        request.name = name
        response = self.call_service(self.configure_client, request)
        if not response.ok:
            raise RuntimeError(f"configure_controller failed: {name}")

    def activate_controllers(self, names):
        print(f"[ControllerLoader] activate {names}")
        request = SwitchController.Request()
        request.activate_controllers = list(names)
        request.deactivate_controllers = []
        request.strictness = 2
        request.activate_asap = True
        request.timeout.sec = 5
        response = self.call_service(self.switch_client, request)
        if not response.ok:
            raise RuntimeError(f"switch_controller failed: {names}")

    def call_service(self, client, request):
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=self.service_timeout_sec)
        if not future.done() or future.result() is None:
            raise RuntimeError(f"service call failed or timed out: {client.srv_name}")
        return future.result()


def main(args=None):
    rclpy.init(args=args)
    node = ControllerLoader()
    try:
        node.run()
        return 0
    except RuntimeError as exc:
        print(f"[ControllerLoader] ERROR: {exc}")
        return 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
