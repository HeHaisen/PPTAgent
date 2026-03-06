"""Test image processing with OpenCV."""

import pytest

OPENCV_SCRIPT = """\
import cv2
import numpy as np

img = np.full((400, 600, 3), 255, dtype=np.uint8)

cv2.rectangle(img, (50, 50), (550, 350), (0, 0, 255), 3)
cv2.circle(img, (300, 200), 100, (0, 255, 0), -1)
cv2.ellipse(img, (300, 200), (150, 80), 45, 0, 360, (255, 0, 0), 2)
cv2.line(img, (50, 50), (550, 350), (255, 0, 255), 2)
cv2.putText(img, 'OpenCV Test', (200, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)

cv2.imwrite('opencv_original.png', img)
cv2.imwrite('opencv_blurred.png', cv2.GaussianBlur(img, (15, 15), 0))
cv2.imwrite('opencv_edges.png', cv2.Canny(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 50, 150))
print('SUCCESS')
"""


@pytest.mark.asyncio
async def test_opencv_processing(agent_env, workspace, tool_call_helper):
    """Test OpenCV: create image, draw shapes, apply filters."""
    write_call = tool_call_helper(
        "write_file",
        {"path": str(workspace / "test_opencv.py"), "content": OPENCV_SCRIPT},
    )
    await agent_env.tool_execute(write_call)

    exec_call = tool_call_helper(
        "execute_command", {"command": f"python {workspace / 'test_opencv.py'}"}
    )
    result = await agent_env.tool_execute(exec_call)
    assert not result.is_error and "SUCCESS" in result.text

    list_call = tool_call_helper("list_directory", {"path": str(workspace)})
    list_result = await agent_env.tool_execute(list_call)
    for f in ["opencv_original.png", "opencv_blurred.png", "opencv_edges.png"]:
        assert f in list_result.text
