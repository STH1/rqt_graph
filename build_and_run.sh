#!/bin/bash
set -e

cd ~/git/rqt_graph_focus

echo "=== Pulling latest changes ==="
git pull

echo "=== Building ==="
source /opt/ros/humble/setup.bash
colcon build --packages-select rqt_graph_focus

echo "=== Sourcing ==="
source install/setup.bash

echo "=== Running ==="
ros2 run rqt_graph_focus rqt_graph_focus --force-discover
