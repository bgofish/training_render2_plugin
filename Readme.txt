Training Render Plugin for LichtFeld Studio
Training Render plugin for LichtFeld Studio. It runs captures images to an image folder during training.

Installation
Manual Installation
Install inside LFS using https://github.com/bgofish/training_render_plugin  this will install to ~/.lichtfeld/plugins/training_render

Capture Methods
1)Current View capture (can be set manually or selecting an image camera from the view or the image list.
2)Circular Camera Track: This uses a json file with the format written from 360_Record
		{
		  "version": 1,
		  "segments": [
			{
			  "type": "orbit",
			  "poi": [
				0.00,
				0.00,
				0.00
			  ],
			  "radius": 1.5,
			  "elevation": -1,
			  "orbit_axis": "y",
			  "start_angle": 0.0,
			  "arc_degrees": 360.0,
			  "duration": 30.0,
			  "invert_direction": false
			}
		  ],
		  "settings": {
			"speed": 1.0,
			"smooth_factor": 0.5,
			"elevation": 1.5,
			"up_axis_idx": 0,
			"invert_elevation": false,
			"resolution_idx": 0,
			"fps": 30.0,
			"fov": 60.0,
			"preview_speed": 1.0
		  }
		}
		
3)Multi-Segment Camera Tracks - Combination of arcs & straights using the format written from 360_Record

4)LFS Camera Path - Camera Keyframe format json file written from the Main Program
