cmake_minimum_required(VERSION 3.8)
project(shelfa_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# 의존성 찾기
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(action_msgs REQUIRED)

# srv 및 action 파일들을 파이썬 모듈로 자동 빌드
rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/FindBookGrasp.srv"
  "srv/PickBookFromShelf.srv"
  "srv/PlaceBookInStorage.srv"
  "action/ExecuteGrasp.action"
  DEPENDENCIES geometry_msgs action_msgs
)

ament_package()
