#!/usr/bin/env python3

from dataclasses import dataclass, field
import time
from typing import Any, Dict, Optional

import rclpy
from dsr_msgs2.srv import MoveJoint, MoveLine

try:
    from dsr_gripper_tcp_interfaces.srv import GetState, SetPosition, SetTorque
except ImportError:
    GetState = None
    SetPosition = None
    SetTorque = None


@dataclass
class BookPickSequenceConfig:
    enable_gripper_control: bool
    dry_run: bool
    gripper_timeout_sec: float
    gripper_open_position: int
    gripper_open_position_2: int
    gripper_soft_grip_position: int
    gripper_hard_grip_position: int
    gripper_require_ready: bool
    gripper_require_torque_enabled: bool
    pick_axis: str
    pick_axis_sign: float
    insert1_mm: float
    pull1_mm: float
    insert2_mm: float
    pull_final_mm: float
    pick_step_max_mm: float
    pick_vel_linear: float
    pick_vel_angular: float
    pick_acc_linear: float
    pick_acc_angular: float
    return_to_start_pose: bool
    return_vel_linear: float
    return_vel_angular: float
    return_acc_linear: float
    return_acc_angular: float
    enable_place_to_box: bool
    box_joint_pose_deg: list
    box_movej_vel: float
    box_movej_acc: float
    place_drop_distance_mm: float


@dataclass
class BookPickSequenceResult:
    success: bool
    aborted_reason: str
    stage_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    gripper_ready: Optional[bool] = None
    gripper_torque_enabled: Optional[bool] = None
    gripper_open_success: bool = False
    gripper_soft_grip_success: bool = False
    gripper_hard_grip_success: bool = False
    final_pull_executed: bool = False
    start_tcp_posx_mm_deg: Optional[list] = None
    return_to_start_pose: bool = False
    return_pose_executed: bool = False
    return_pose_success: bool = False
    return_pose_aborted_reason: str = ""
    return_move_line_pos: Optional[list] = None
    return_vel_linear: float = 0.0
    return_acc_linear: float = 0.0
    place_sequence_executed: bool = False
    place_sequence_success: bool = False
    box_joint_pose_deg: Optional[list] = None
    human_readable_summary: Dict[str, str] = field(default_factory=dict)


class BookPickSequenceExecutor:
    def __init__(
        self,
        node,
        config: BookPickSequenceConfig,
        move_joint_client,
        move_joint_service: str,
        move_line_client,
        move_line_service: str,
        gripper_state_client,
        gripper_state_service: str,
        gripper_set_torque_client,
        gripper_set_torque_service: str,
        gripper_set_position_client,
        gripper_set_position_service: str,
        start_tcp_posx_mm_deg=None,
    ):
        self.node = node
        self.config = config
        self.move_joint_client = move_joint_client
        self.move_joint_service = move_joint_service
        self.move_line_client = move_line_client
        self.move_line_service = move_line_service
        self.gripper_state_client = gripper_state_client
        self.gripper_state_service = gripper_state_service
        self.gripper_set_torque_client = gripper_set_torque_client
        self.gripper_set_torque_service = gripper_set_torque_service
        self.gripper_set_position_client = gripper_set_position_client
        self.gripper_set_position_service = gripper_set_position_service
        self.last_gripper_state = None
        self.result = BookPickSequenceResult(success=False, aborted_reason="")
        self.result.start_tcp_posx_mm_deg = (
            None if start_tcp_posx_mm_deg is None else [float(v) for v in start_tcp_posx_mm_deg]
        )
        self.result.return_to_start_pose = bool(self.config.return_to_start_pose)
        self.result.return_vel_linear = float(self.config.return_vel_linear)
        self.result.return_acc_linear = float(self.config.return_acc_linear)
        self.result.box_joint_pose_deg = [float(v) for v in self.config.box_joint_pose_deg]
        self.result.human_readable_summary = self.build_human_readable_summary()

    def build_human_readable_summary(self) -> Dict[str, str]:
        return {
            "insert1": (
                f"1차 들어가기 {int(self.config.insert1_mm)}mm, 1회 이동"
            ),
            "pull1": (
                f"1차 빼기 {int(self.config.pull1_mm)}mm, 1회 이동"
            ),
            "insert2": (
                f"2차 들어가기 {int(self.config.insert2_mm)}mm, 1회 이동"
            ),
            "pull_final": (
                f"2차 빼기 {int(self.config.pull_final_mm)}mm, 1회 이동"
            ),
            "grip": (
                f"open1={int(self.config.gripper_open_position)}, "
                f"open2={int(self.config.gripper_open_position_2)}, "
                f"soft={int(self.config.gripper_soft_grip_position)}, "
                f"hard={int(self.config.gripper_hard_grip_position)}"
            ),
            "speed": (
                f"vel={self.config.pick_vel_linear:.1f}, "
                f"acc={self.config.pick_acc_linear:.1f}"
            ),
            "return": (
                "책을 잡은 상태로 시작 자세 복귀"
                if self.config.return_to_start_pose
                else "복귀 비활성화"
            ),
            "place": (
                f"박스 배치={'활성화' if self.config.enable_place_to_box else '비활성화'}, "
                f"box_joint={self.config.box_joint_pose_deg}, "
                f"drop={int(self.config.place_drop_distance_mm)}mm"
            ),
        }

    def log_sequence_header(self):
        self.log_info(
            "\n"
            "[책 빼기 시퀀스 시작]\n"
            "현재 설정:\n"
            f"- 1차 들어가기: {self.config.insert1_mm:.0f}mm\n"
            f"- 1차 빼기: {self.config.pull1_mm:.0f}mm\n"
            f"- 2차 들어가기: {self.config.insert2_mm:.0f}mm\n"
            f"- 2차 빼기: {self.config.pull_final_mm:.0f}mm\n"
            f"- 이동 축: {self.config.pick_axis}\n"
            f"- 방향 부호: {self.config.pick_axis_sign:+.1f}\n"
            "- 각 insert/pull 단계: 1회 이동\n"
            f"- 그리퍼 open: {self.config.gripper_open_position}\n"
            f"- 2차 진입 전 open: {self.config.gripper_open_position_2}\n"
            f"- soft grip: {self.config.gripper_soft_grip_position}\n"
            f"- hard grip: {self.config.gripper_hard_grip_position}\n"
            f"- 이동 속도: vel={self.config.pick_vel_linear:.1f}, acc={self.config.pick_acc_linear:.1f}\n"
            f"- 시작 자세 복귀: {self.config.return_to_start_pose}\n"
            f"- 박스 배치: {self.config.enable_place_to_box}\n"
            f"- 박스 joint: {self.config.box_joint_pose_deg}\n"
            f"- 박스 내려놓기 거리: {self.config.place_drop_distance_mm:.0f}mm"
        )

    def run(self) -> BookPickSequenceResult:
        self.log_sequence_header()
        if not self.config.dry_run and not self.config.enable_gripper_control:
            return self.abort("gripper_control_disabled")

        if not self.check_gripper_ready():
            return self.result
        if not self.torque_on():
            return self.result
        if not self.set_gripper_position(
            self.config.gripper_open_position,
            "PICK_OPEN_GRIPPER",
        ):
            return self.result
        if not self.move_relative_axis(self.config.insert1_mm, "PICK_INSERT_1"):
            return self.result
        if not self.set_gripper_position(
            self.config.gripper_soft_grip_position,
            "PICK_SOFT_GRIP",
        ):
            return self.result
        if not self.move_relative_axis(-self.config.pull1_mm, "PICK_PULL_1"):
            return self.result
        if not self.set_gripper_position(
            self.config.gripper_open_position_2,
            "PICK_OPEN_GRIPPER_2",
        ):
            return self.result
        if not self.move_relative_axis(self.config.insert2_mm, "PICK_INSERT_2"):
            return self.result
        if not self.set_gripper_position(
            self.config.gripper_hard_grip_position,
            "PICK_HARD_GRIP",
        ):
            return self.result
        if not self.config.dry_run:
            state = self.read_gripper_state()
            if state is None:
                return self.result
            self.record_stage(
                "PICK_HARD_GRIP_STATE",
                success=True,
                gripper_state=self.serialize_gripper_state(state),
            )
        if not self.move_relative_axis(-self.config.pull_final_mm, "PICK_PULL_FINAL"):
            return self.result
        if self.config.enable_place_to_box:
            if not self.run_place_to_box_sequence():
                return self.result
        elif self.config.return_to_start_pose:
            if not self.return_to_start_pose():
                return self.result

        self.result.success = True
        self.result.aborted_reason = ""
        self.record_stage("DONE_PICK", success=True)
        self.log_info("\n[책 빼기 시퀀스 완료]")
        return self.result

    def abort(self, reason: str) -> BookPickSequenceResult:
        self.result.success = False
        self.result.aborted_reason = str(reason)
        self.record_stage("ABORT", success=False, reason=str(reason))
        self.node.get_logger().error(f"Pick sequence aborted: {reason}")
        return self.result

    def log_info(self, message: str):
        if hasattr(self.node, "log_info"):
            self.node.log_info(message)
            return
        logger = self.node.get_logger()
        if hasattr(logger, "info"):
            logger.info(message)
        elif hasattr(logger, "dinfo"):
            logger.dinfo(message)
        else:
            logger.warn(message)

    def record_stage(self, stage_name: str, **kwargs):
        stage_result = {
            "stage": stage_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        stage_result.update(kwargs)
        self.result.stage_results[stage_name] = stage_result

    def serialize_gripper_state(self, state) -> Optional[Dict[str, Any]]:
        if state is None:
            return None
        return {
            "ready": bool(getattr(state, "ready", False)),
            "torque_enabled": bool(getattr(state, "torque_enabled", False)),
            "moving": bool(getattr(state, "moving", False)),
            "in_position": bool(getattr(state, "in_position", False)),
            "present_position": int(getattr(state, "present_position", 0)),
            "goal_position": int(getattr(state, "goal_position", 0)),
            "present_current": int(getattr(state, "present_current", 0)),
            "status_text": str(getattr(state, "status_text", "")),
        }

    def current_gripper_state_snapshot(self) -> Optional[Dict[str, Any]]:
        return self.serialize_gripper_state(self.last_gripper_state)

    def wait_for_future(self, future, timeout_sec: float, label: str) -> bool:
        start_time = time.monotonic()
        while rclpy.ok() and not future.done():
            if time.monotonic() - start_time > timeout_sec:
                self.abort(f"{label.lower()}_timeout")
                return False
            rclpy.spin_once(self.node, timeout_sec=0.05)
        return future.done()

    def read_gripper_state(self):
        if GetState is None:
            self.abort("gripper_get_state_interface_unavailable")
            return None
        if self.gripper_state_client is None:
            self.abort("gripper_get_state_client_unavailable")
            return None

        request = GetState.Request()
        request.force_read = True
        self.log_info(
            "\n"
            "PICK_CHECK_GRIPPER_READY\n"
            "  stage=PICK_CHECK_GRIPPER_READY\n"
            f"  service={self.gripper_state_service}\n"
            "  force_read=true"
        )
        if self.config.dry_run:
            self.record_stage(
                "PICK_CHECK_GRIPPER_READY",
                success=True,
                dry_run=True,
                service=self.gripper_state_service,
            )
            return None

        if not self.gripper_state_client.wait_for_service(timeout_sec=1.0):
            self.abort("gripper_state_service_unavailable")
            return None

        future = self.gripper_state_client.call_async(request)
        if not self.wait_for_future(
            future,
            self.config.gripper_timeout_sec,
            "gripper_state",
        ):
            return None

        if future.result() is None:
            self.abort(f"gripper_state_failed:{future.exception()}")
            return None

        response = future.result()
        if not bool(response.success):
            self.abort(f"gripper_state_unsuccessful:{response.message}")
            return None

        self.last_gripper_state = response.state
        self.result.gripper_ready = bool(getattr(response.state, "ready", False))
        self.result.gripper_torque_enabled = bool(
            getattr(response.state, "torque_enabled", False)
        )
        self.record_stage(
            "PICK_CHECK_GRIPPER_READY",
            success=True,
            dry_run=False,
            ready=self.result.gripper_ready,
            torque_enabled=self.result.gripper_torque_enabled,
            present_position=int(getattr(response.state, "present_position", 0)),
            present_current=int(getattr(response.state, "present_current", 0)),
            status_text=str(getattr(response.state, "status_text", "")),
            gripper_state=self.serialize_gripper_state(response.state),
        )
        return response.state

    def call_gripper_service(self, client, service_name: str, request, label: str) -> bool:
        if client is None:
            self.abort(f"{label.lower()}_client_unavailable")
            return False
        if not client.wait_for_service(timeout_sec=1.0):
            self.abort(f"{label.lower()}_service_unavailable")
            return False

        self.node.get_logger().warn(f"Calling {service_name}")
        future = client.call_async(request)
        if not self.wait_for_future(
            future,
            self.config.gripper_timeout_sec,
            label,
        ):
            return False

        if future.result() is None:
            self.abort(f"{label.lower()}_failed:{future.exception()}")
            return False

        response = future.result()
        message = str(getattr(response, "message", ""))
        state = getattr(response, "state", None)
        if state is not None:
            self.last_gripper_state = state
            self.result.gripper_ready = bool(getattr(state, "ready", False))
            self.result.gripper_torque_enabled = bool(getattr(state, "torque_enabled", False))
        if not bool(response.success):
            self.abort(f"{label.lower()}_unsuccessful:{message}")
            return False

        self.log_info(
            "\n"
            f"{label} service response\n"
            "  success=True\n"
            f"  message={message}\n"
            f"  current_gripper_state={self.current_gripper_state_snapshot()}"
        )
        return True

    def check_gripper_ready(self) -> bool:
        state = self.read_gripper_state()
        if self.config.dry_run:
            return True
        if state is None:
            return False

        ready = bool(getattr(state, "ready", False))
        torque_enabled = bool(getattr(state, "torque_enabled", False))
        self.log_info(
            "\n"
            "Pick check gripper ready\n"
            "  stage=PICK_CHECK_GRIPPER_READY\n"
            f"  ready={ready}\n"
            f"  torque_enabled={torque_enabled}\n"
            f"  present_position={int(getattr(state, 'present_position', 0))}\n"
            f"  present_current={int(getattr(state, 'present_current', 0))}\n"
            f"  status_text={getattr(state, 'status_text', '')}"
        )
        if self.config.gripper_require_ready and not ready:
            self.abort("gripper_not_ready")
            return False
        return True

    def torque_on(self) -> bool:
        if SetTorque is None:
            self.abort("gripper_set_torque_interface_unavailable")
            return False
        request = SetTorque.Request()
        request.enabled = True
        self.log_info("\n[1단계] 그리퍼 토크 켜기\n→ enabled=true")
        self.log_info(
            "\n"
            "PICK_TORQUE_ON\n"
            "  stage=PICK_TORQUE_ON\n"
            f"  service={self.gripper_set_torque_service}\n"
            "  enabled=true"
        )
        if self.config.dry_run:
            self.record_stage("PICK_TORQUE_ON", success=True, dry_run=True, enabled=True)
            return True
        if not self.call_gripper_service(
            self.gripper_set_torque_client,
            self.gripper_set_torque_service,
            request,
            "SetTorque",
        ):
            return False
        self.result.gripper_torque_enabled = True
        self.record_stage(
            "PICK_TORQUE_ON",
            success=True,
            dry_run=False,
            enabled=True,
            gripper_state=self.current_gripper_state_snapshot(),
        )
        return True

    def set_gripper_position(self, position: int, label: str) -> bool:
        if SetPosition is None:
            self.abort("gripper_set_position_interface_unavailable")
            return False
        request = SetPosition.Request()
        request.position = int(position)
        request.timeout_sec = float(self.config.gripper_timeout_sec)
        stage_messages = {
            "PREPARE_GRIPPER_VIEW": f"\n[시야 확보] 그리퍼를 카메라 시야 밖으로 이동\n→ 목표 위치: {int(position)}",
            "PREPARE_GRIPPER_PICK_OPEN": f"\n[접근 준비] 잡기 전에 그리퍼를 기존 open 위치로 복귀\n→ 목표 위치: {int(position)}",
            "PICK_OPEN_GRIPPER": f"\n[1단계] 그리퍼 열기\n→ 목표 위치: {int(position)}",
            "PICK_SOFT_GRIP": f"\n[3단계] 1차 잡기\n→ soft grip 위치: {int(position)}",
            "PICK_OPEN_GRIPPER_2": f"\n[5단계] 다시 그리퍼 열기\n→ 목표 위치: {int(position)}",
            "PICK_HARD_GRIP": f"\n[7단계] 2차 강하게 잡기\n→ hard grip 위치: {int(position)}",
            "PLACE_OPEN_GRIPPER": f"\n[11단계] 박스에 책 내려놓기\n→ open 위치: {int(position)}",
        }
        human_message = stage_messages.get(label)
        if human_message:
            self.log_info(human_message)
        self.log_info(
            "\n"
            f"{label}\n"
            f"  stage={label}\n"
            f"  service={self.gripper_set_position_service}\n"
            f"  gripper target position={int(position)}\n"
            f"  timeout_sec={self.config.gripper_timeout_sec:.2f}"
        )
        if self.config.dry_run:
            self.record_stage(
                label,
                success=True,
                dry_run=True,
                gripper_target_position=int(position),
            )
            return True
        if not self.call_gripper_service(
            self.gripper_set_position_client,
            self.gripper_set_position_service,
            request,
            "SetPosition",
        ):
            return False
        self.record_stage(
            label,
            success=True,
            dry_run=False,
            gripper_target_position=int(position),
            gripper_state=self.current_gripper_state_snapshot(),
        )
        if label == "PICK_OPEN_GRIPPER":
            self.result.gripper_open_success = True
        elif label == "PICK_SOFT_GRIP":
            self.result.gripper_soft_grip_success = True
        elif label == "PICK_HARD_GRIP":
            self.result.gripper_hard_grip_success = True
        return True

    def move_relative_axis(self, distance_mm: float, label: str) -> bool:
        total_signed_mm = float(self.config.pick_axis_sign) * float(distance_mm)
        axis_index = {"x": 0, "y": 1, "z": 2}.get(self.config.pick_axis)
        if axis_index is None:
            self.abort(f"invalid_pick_axis:{self.config.pick_axis}")
            return False

        requested_total_mm = float(distance_mm)
        stage_headers = {
            "PICK_INSERT_1": "[2단계] 1차 들어가기",
            "PICK_PULL_1": "[4단계] 1차 빼기",
            "PICK_INSERT_2": "[6단계] 2차 들어가기",
            "PICK_PULL_FINAL": "[8단계] 2차 빼기",
        }
        self.log_info(
            "\n"
            f"{stage_headers.get(label, label)}\n"
            f"→ 총 {abs(requested_total_mm):.0f}mm 이동\n"
            "→ 1회 이동"
        )

        request = MoveLine.Request()
        request.pos = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        request.pos[axis_index] = float(total_signed_mm)
        request.vel = [self.config.pick_vel_linear, self.config.pick_vel_angular]
        request.acc = [self.config.pick_acc_linear, self.config.pick_acc_angular]
        self.node.fill_moveline_common(request)
        gripper_state = self.current_gripper_state_snapshot()

        self.log_info(
            "\n"
            f"{label}\n"
            f"  stage={label}\n"
            f"  requested_distance_mm={requested_total_mm:.3f}\n"
            f"  move_mm={total_signed_mm:.3f}\n"
            f"  pick_axis={self.config.pick_axis}\n"
            f"  pick_axis_sign={self.config.pick_axis_sign:.1f}\n"
            f"  MoveLine pos [mm,deg]={request.pos}\n"
            f"  gripper state snapshot={gripper_state}"
        )

        success = True
        if self.config.dry_run:
            self.log_info(f"{label} dry_run: skipped MoveLine call")
        else:
            success = self.node.call_service(
                self.move_line_client,
                self.move_line_service,
                request,
                f"MoveLine[{label}]",
            )

        if not success:
            self.record_stage(
                label,
                success=False,
                dry_run=False,
                requested_distance_mm=float(requested_total_mm),
                executed_distance_mm=0.0,
                pick_step_max_mm=float(self.config.pick_step_max_mm),
                total_steps=1,
                failed_step_index=1,
                pick_axis=self.config.pick_axis,
                pick_axis_sign=float(self.config.pick_axis_sign),
                sub_steps=[
                    {
                        "step_index": 1,
                        "total_steps": 1,
                        "requested_total_mm": float(requested_total_mm),
                        "step_mm": float(total_signed_mm),
                        "move_line_pos": list(request.pos),
                        "success": False,
                    }
                ],
                current_gripper_state=gripper_state,
            )
            self.abort(f"{label.lower()}_moveline_failed_step_1")
            return False

        self.record_stage(
            label,
            success=True,
            dry_run=bool(self.config.dry_run),
            requested_distance_mm=float(requested_total_mm),
            executed_distance_mm=float(total_signed_mm),
            pick_step_max_mm=float(self.config.pick_step_max_mm),
            total_steps=1,
            pick_axis=self.config.pick_axis,
            pick_axis_sign=float(self.config.pick_axis_sign),
            sub_steps=[
                {
                    "step_index": 1,
                    "total_steps": 1,
                    "requested_total_mm": float(requested_total_mm),
                    "step_mm": float(total_signed_mm),
                    "move_line_pos": list(request.pos),
                    "success": True,
                }
            ],
            current_gripper_state=self.current_gripper_state_snapshot(),
        )
        if label == "PICK_PULL_FINAL":
            self.result.final_pull_executed = True
        return True

    def move_to_box_joint(self) -> bool:
        request = MoveJoint.Request()
        request.pos = [float(v) for v in self.config.box_joint_pose_deg]
        request.vel = float(self.config.box_movej_vel)
        request.acc = float(self.config.box_movej_acc)
        request.time = 0.0
        request.radius = 0.0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0

        self.log_info(
            "\n"
            "[9단계] 박스 위치로 이동\n"
            f"→ 목표 joint: {request.pos}"
        )
        self.log_info(
            "\n"
            "MOVE_TO_BOX_JOINT\n"
            "  stage=MOVE_TO_BOX_JOINT\n"
            f"  target_joint_deg={request.pos}\n"
            f"  vel={request.vel}\n"
            f"  acc={request.acc}"
        )

        if self.config.dry_run:
            self.result.place_sequence_executed = True
            self.record_stage(
                "MOVE_TO_BOX_JOINT",
                success=True,
                dry_run=True,
                target_joint_deg=list(request.pos),
            )
            return True

        ok = self.node.call_service(
            self.move_joint_client,
            self.move_joint_service,
            request,
            "MoveJoint[MOVE_TO_BOX_JOINT]",
        )
        if not ok:
            self.record_stage(
                "MOVE_TO_BOX_JOINT",
                success=False,
                dry_run=False,
                target_joint_deg=list(request.pos),
            )
            self.abort("move_to_box_joint_failed")
            return False

        self.result.place_sequence_executed = True
        self.record_stage(
            "MOVE_TO_BOX_JOINT",
            success=True,
            dry_run=False,
            target_joint_deg=list(request.pos),
        )
        return True

    def move_tool_z_for_place(self, distance_mm: float, label: str, human_title: str) -> bool:
        request = MoveLine.Request()
        request.pos = [0.0, 0.0, float(distance_mm), 0.0, 0.0, 0.0]
        request.vel = [self.config.pick_vel_linear, self.config.pick_vel_angular]
        request.acc = [self.config.pick_acc_linear, self.config.pick_acc_angular]
        self.node.fill_moveline_common(request)

        self.log_info(
            "\n"
            f"{human_title}\n"
            f"→ tool z 이동: {distance_mm:+.0f}mm"
        )
        self.log_info(
            "\n"
            f"{label}\n"
            f"  stage={label}\n"
            f"  move_tool_z_mm={distance_mm:.3f}\n"
            f"  MoveLine pos [mm,deg]={request.pos}"
        )

        if self.config.dry_run:
            self.record_stage(
                label,
                success=True,
                dry_run=True,
                move_tool_z_mm=float(distance_mm),
                move_line_pos=list(request.pos),
            )
            return True

        ok = self.node.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            f"MoveLine[{label}]",
        )
        if not ok:
            self.record_stage(
                label,
                success=False,
                dry_run=False,
                move_tool_z_mm=float(distance_mm),
                move_line_pos=list(request.pos),
            )
            self.abort(f"{label.lower()}_failed")
            return False

        self.record_stage(
            label,
            success=True,
            dry_run=False,
            move_tool_z_mm=float(distance_mm),
            move_line_pos=list(request.pos),
        )
        return True

    def run_place_to_box_sequence(self) -> bool:
        if not self.move_to_box_joint():
            return False
        if not self.move_tool_z_for_place(
            self.config.place_drop_distance_mm,
            "PLACE_LOWER_TO_BOX",
            "[10단계] 박스로 내려가기",
        ):
            return False
        if not self.set_gripper_position(
            self.config.gripper_open_position,
            "PLACE_OPEN_GRIPPER",
        ):
            return False
        if not self.move_tool_z_for_place(
            -self.config.place_drop_distance_mm,
            "PLACE_RAISE_FROM_BOX",
            "[12단계] 박스에서 다시 올라오기",
        ):
            return False
        self.result.place_sequence_success = True
        self.record_stage("DONE_PLACE", success=True)
        self.log_info("\n[박스 배치 시퀀스 완료]")
        return True

    def return_to_start_pose(self) -> bool:
        if not self.result.start_tcp_posx_mm_deg:
            self.result.return_pose_aborted_reason = "start_tcp_pose_unavailable"
            self.record_stage(
                "PICK_RETURN_TO_START_POSE",
                success=False,
                reason=self.result.return_pose_aborted_reason,
            )
            self.log_info("\n[9단계] 책 정렬 후 자세로 복귀\n→ 시작 자세 저장 실패로 복귀를 건너뜁니다.")
            return True

        request = MoveLine.Request()
        request.pos = list(self.result.start_tcp_posx_mm_deg)
        request.vel = [self.config.return_vel_linear, self.config.return_vel_angular]
        request.acc = [self.config.return_acc_linear, self.config.return_acc_angular]
        request.time = 0.0
        request.radius = 0.0
        request.ref = 0
        request.mode = 0
        request.blend_type = 0
        request.sync_type = 0
        self.result.return_move_line_pos = list(request.pos)

        self.log_info(
            "\n"
            "[9단계] 책 정렬 후 자세로 복귀\n"
            "→ 정렬 후 저장된 TCP 자세 또는 시작 자세로 복귀"
        )
        self.log_info(
            "\n"
            "PICK_RETURN_TO_START_POSE\n"
            "  stage=PICK_RETURN_TO_START_POSE\n"
            f"  target_pos_mm_deg={request.pos}\n"
            f"  vel={request.vel}\n"
            f"  acc={request.acc}\n"
            f"  ref={request.ref}\n"
            f"  mode={request.mode}"
        )

        if self.config.dry_run:
            self.result.return_pose_executed = True
            self.result.return_pose_success = True
            self.record_stage(
                "PICK_RETURN_TO_START_POSE",
                success=True,
                dry_run=True,
                return_move_line_pos=list(request.pos),
            )
            return True

        ok = self.node.call_service(
            self.move_line_client,
            self.move_line_service,
            request,
            "MoveLine[PICK_RETURN_TO_START_POSE]",
        )
        self.result.return_pose_executed = True
        self.result.return_pose_success = bool(ok)
        if not ok:
            self.result.return_pose_aborted_reason = "return_move_line_failed"
            self.record_stage(
                "PICK_RETURN_TO_START_POSE",
                success=False,
                dry_run=False,
                reason=self.result.return_pose_aborted_reason,
                return_move_line_pos=list(request.pos),
            )
            self.abort("pick_return_to_start_pose_failed")
            return False

        self.record_stage(
            "PICK_RETURN_TO_START_POSE",
            success=True,
            dry_run=False,
            return_move_line_pos=list(request.pos),
        )
        return True
