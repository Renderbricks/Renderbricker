"""Entry of the runs without a window and of the background Blenders:
blender -b <scene.blend> --python rbcore/run.py -- <result.blend> [--view-level 1 --render-level 2 --jobs auto ...]"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rbcore                               # noqa: E402  (the package beside this file)

rbcore.headless.main()
