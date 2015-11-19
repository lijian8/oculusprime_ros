#!/usr/bin/env python

"""
on any new /initialpose, do full rotation, then delay (to hone in amcl)

follow something ~15th pose in global path for all moves (about 0.3m away?)
    -maximum path length seems to be about 35*5 (45*5 max) for 2-3 meter path
    -(longer if more turns -- go for 15th or 20th pose, or max if less, should be OK)

ignore local path, except for determining if at goal or not
	if no recent local path, must be at goal: followpath = False, goalpose = true

requires dwa_base_controller, global path updated continuously as bot moves

"""


import rospy, tf
import oculusprimesocket
from nav_msgs.msg import Odometry
import math
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseWithCovarianceStamped
from actionlib_msgs.msg import GoalStatusArray
from move_base_msgs.msg import MoveBaseActionGoal

listentime = 0.1 # 0.6 # allows odom + amcl to catch up
nextmove = 0
odomx = 0
odomy = 0
odomth = 0
targetx = 0	
targety = 0
targetth = 0
followpath = False
pathid = None
goalth = 0 
initialturn = False
waitonaboutface = 0
minturn = math.radians(8) # (was 6) -- 0.21 minimum for pwm 255
minlinear = 0.08 # was 0.05
maxlinear = 0.5
maxarclinear = 0.75
lastpath = 0  # refers to localpath
goalpose = False
goalseek = False
meterspersec = 0.33 # linear speed  TODO: get from java
radianspersec = 1.496
tfth = 0
globalpathposenum = 20  
listener = None


def pathCallback(data): # local path
	global goalpose, lastpath
	global targetx, targety, targetth 
	
	lastpath = rospy.get_time()
	goalpose = False
	
	# if initialturn:
		# return	
		
	# p = data.poses[len(data.poses)-1] # get latest pose
	# targetx = p.pose.position.x
	# targety = p.pose.position.y
	# quaternion = ( p.pose.orientation.x, p.pose.orientation.y,
	# p.pose.orientation.z, p.pose.orientation.w )
	# targetth = tf.transformations.euler_from_quaternion(quaternion)[2]
	
def globalPathCallback(data):
	global targetx, targety, targetth , followpath, pathid
	
	n = len(data.poses)
	if n < 5:
		return

	followpath = True

	# if not initialturn:
		# return
		
	if n-1 < globalpathposenum:
		p = data.poses[n-1] 
	else:
		p = data.poses[globalpathposenum]
	
	targetx = p.pose.position.x
	targety = p.pose.position.y
	quaternion = ( p.pose.orientation.x, p.pose.orientation.y,
	p.pose.orientation.z, p.pose.orientation.w )
	targetth = tf.transformations.euler_from_quaternion(quaternion)[2]
	
	pathid = data.header.seq

def odomCallback(data):
	global odomx, odomy, odomth
	odomx = data.pose.pose.position.x
	odomy = data.pose.pose.position.y
	quaternion = ( data.pose.pose.orientation.x, data.pose.pose.orientation.y,
	data.pose.pose.orientation.z, data.pose.pose.orientation.w )
	odomth = tf.transformations.euler_from_quaternion(quaternion)[2]
	
	# determine direction (angle) on map
	global tfth, listener	 
	try:
		(trans,rot) = listener.lookupTransform('/map', '/odom', rospy.Time(0))
		quaternion = (rot[0], rot[1], rot[2], rot[3])
		tfth = tf.transformations.euler_from_quaternion(quaternion)[2]
	except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
		pass	

def intialPoseCallback(data):
	if data.pose.pose.position.x == 0 and data.pose.pose.position.y == 0:
		return
	# do full rotation on pose estimate, to hone-in amcl (if not docked)
	rospy.sleep(0.5) # let amcl settle
	oculusprimesocket.clearIncoming()  # why?
	oculusprimesocket.sendString("right 360")
	oculusprimesocket.waitForReplySearch("<state> direction stop")

	
def goalCallback(d):
	global goalth, goalpose, lastpath, initialturn, followpath, nextmove

	# to prevent immediately rotating wrongly towards new goal direction 
	lastpath = rospy.get_time()
	goalpose = False

	# set goal angle
	data = d.goal.target_pose
	quaternion = ( data.pose.orientation.x, data.pose.orientation.y,
	data.pose.orientation.z, data.pose.orientation.w )
	goalth = tf.transformations.euler_from_quaternion(quaternion)[2]
	initialturn = True
	followpath = False
	nextmove = lastpath + 2 # sometimes globalpath still points at previoius goal
	
def goalStatusCallback(data):
	global goalseek
	goalseek = False
	if len(data.status_list) == 0:
		return
	status = data.status_list[len(data.status_list)-1] # get latest status
	if status.status == 1:
		goalseek = True
				
def arcmove(ox, oy, oth, tx, ty, tth, gth):
	"""
	scenarios:
	-initial turn (usually going to want to rotate in place, then go) USE SAME
	   -stopbetweenmoves true, turn to point to target, stopbetweenmoves false, linear move
	-normal global path following (arc move)  NEW
	   -stopbetweenmoves false, arcmove dist angle
	   - TODO: should rotate in place beyond maximum angle???
	-goal pose final turn (rotate in place)-- was determined by reaching location and 
	    no more local paths published for 3 seconds... global path shouldn't include goal pose?  USE SAME
	    -stopbetweenmoves true, turn to pose
	-obstacle (potentially a sudden large angle! was using 120 deg from current pose)
		-if angle > 90? do linear move instead then wait (stopbetweenmoves true first?)
	"""
	
	global initialturn, waitonaboutface, nextmove
	# global followpath, goalpose, tfth, pathid
	# global odomx, odomy, odomth
	
	# find arclength if any, and turn radians, depending on scenario
	arclength = 0
	goalrotate = False	
	if followpath and not ox==tx and not oy==ty and not initialturn: # normal arc move
		dx = tx - ox
		dy = ty - oy	
		distance = math.sqrt( pow(dx,2) + pow(dy,2) )
		th = math.acos(dx/distance)
		if dy <0:
			th = -th

		dth = th - oth
		if dth > math.pi:
			dth = -math.pi*2 + dth
		elif dth < -math.pi:
			dth = math.pi*2 + dth

		radius = (distance/2)/math.sin(dth/2)
		arclength = radius * dth # *should* work out to always be > 0
		if abs(dth/arclength) > 2.5: #  1.57:
			arclength = 0
			print ("dpm > 70")
		else: 
			print("arclength>0")
	elif goalpose:  # final goal rotate move
		dth = (gth - tfth)-oth
		goalrotate = True
		print("goalrotate")
	else: # initial turn move (always?)  
		dx = tx - ox
		dy = ty - oy	
		distance = math.sqrt( pow(dx,2) + pow(dy,2) )
		th = math.acos(dx/distance)
		if dy <0:
			th = -th

		dth = th - oth
		if initialturn:
			initialturn = False
			print("initialturn")
		else:
			print("not initialturn")

	# determine angle delta for move
	if dth > math.pi:
		dth = -math.pi*2 + dth
	elif dth < -math.pi:
		dth = math.pi*2 + dth
		
	# if turning more than 120 deg, inch forward, make sure not transient obstacle (like door transfer)
	# TODO: skip if within 3 feet of goal?!
	# if abs(dth) > 2.0944 and not goalrotate and not initialturn and waitonaboutface < 1: 
		# oculusprimesocket.sendString("forward 0.25")
		# oculusprimesocket.waitForReplySearch("<state> direction stop")
		# waitonaboutface += 1 # only do this once
		# rospy.sleep(1)
		# return
	# waitonaboutface = 0

	if arclength > 0: # arcmove
		# force arclength limits	
		if arclength < minlinear:
			arclength = minlinear
		if arclength > maxarclinear:
			arclength = maxarclinear

		oculusprimesocket.sendString("arcmove " + str(distance) + " " + str(int(math.degrees(dth))) ) 
		rospy.sleep(distance/meterspersec)
		print("arcmove " + str(distance) + " " + str(int(math.degrees(dth))) ) 
		nextmove = rospy.get_time()
		return
	
	# rotate only
	# force minimum
	if dth > 0 and dth < minturn:
		dth = minturn
	elif dth < 0 and dth > -minturn:
		dth = -minturn
	
	oculusprimesocket.clearIncoming()

	if dth > 0:
		oculusprimesocket.sendString("left " + str(int(math.degrees(dth))) ) 
		oculusprimesocket.waitForReplySearch("<state> direction stop")
		rospy.sleep(dth/radianspersec)
		print ("left " + str(int(math.degrees(dth))) )
	elif dth < 0:
		oculusprimesocket.sendString("right " +str(int(math.degrees(-dth))) )
		oculusprimesocket.waitForReplySearch("<state> direction stop")
		rospy.sleep(dth/radianspersec)
		print ("right " +str(int(math.degrees(-dth))) )
		
	nextmove = rospy.get_time() + 0.4
	
	
		

def move(ox, oy, oth, tx, ty, tth, gth):
	global followpath, goalpose, tfth, pathid, initialturn, waitonaboutface
	global odomx, odomy, odomth

	currentpathid = pathid

	# determine xy deltas for move
	distance = 0
	if followpath:
		dx = tx - ox
		dy = ty - oy	
		distance = math.sqrt( pow(dx,2) + pow(dy,2) )
	
	goalrotate = False
	if distance > 0:
		th = math.acos(dx/distance)
		if dy <0:
			th = -th
	elif goalpose:
		th = gth - tfth
		goalrotate = True
	else:
		th = tth
	
	# determine angle delta for move
	dth = th - oth
	if dth > math.pi:
		dth = -math.pi*2 + dth
	elif dth < -math.pi:
		dth = math.pi*2 + dth
		
	# force minimums	
	if distance > 0 and distance < minlinear:
		distance = minlinear
		
	if distance > maxlinear:
		distance = maxlinear

	# supposed to reduce zig zagging  (was 0.3)
	if dth < minturn*0.5 and dth > -minturn*0.5:
		dth = 0
	elif dth >= minturn*0.5 and dth < minturn:
		dth = minturn
	elif dth <= -minturn*0.5 and dth > -minturn:
		dth = -minturn

	oculusprimesocket.clearIncoming()

	# if turning more than 120 deg, inch forward, make sure not transient obstacle (like door transfer)
	if abs(dth) > 2.0944 and not goalrotate and not initialturn and waitonaboutface < 1: 
		oculusprimesocket.sendString("forward 0.25")
		oculusprimesocket.waitForReplySearch("<state> direction stop")
		waitonaboutface += 1 # only do this once
		rospy.sleep(1)
		return
		
	waitonaboutface = 0

	if not pathid == currentpathid:
		return

	if dth > 0:
		oculusprimesocket.sendString("left " + str(int(math.degrees(dth))) ) 
		oculusprimesocket.waitForReplySearch("<state> direction stop")
	elif dth < 0:
		oculusprimesocket.sendString("right " +str(int(math.degrees(-dth))) )
		oculusprimesocket.waitForReplySearch("<state> direction stop")

	if distance > 0:
		oculusprimesocket.sendString("forward "+str(distance))
		rospy.sleep(distance/meterspersec)
		initialturn = False

	# if goalrotate:
		# rospy.sleep(1) 
		
			
def cleanup():
	# oculusprimesocket.sendString("move stop")
	# oculusprimesocket.sendString("state delete navigationenabled")
	oculusprimesocket.sendString("log arcmove_globalpath_follower.py disconnecting")   


# MAIN

# rospy.init_node('dwa_base_controller', anonymous=False)
rospy.init_node('global_path_follower', anonymous=False)
listener = tf.TransformListener()
oculusprimesocket.connect()
rospy.on_shutdown(cleanup)

rospy.Subscriber("odom", Odometry, odomCallback)
rospy.Subscriber("move_base/DWAPlannerROS/local_plan", Path, pathCallback)
rospy.Subscriber("move_base/goal", MoveBaseActionGoal, goalCallback)
rospy.Subscriber("move_base/status", GoalStatusArray, goalStatusCallback)
rospy.Subscriber("move_base/DWAPlannerROS/global_plan", Path, globalPathCallback)
rospy.Subscriber("initialpose", PoseWithCovarianceStamped, intialPoseCallback)

oculusprimesocket.sendString("log arcmove_globalpath_follower.py connected") 

# oculusprimesocket.sendString("speed "+str(linearspeed) )

while not rospy.is_shutdown():
	t = rospy.get_time()
	
	if t >= nextmove:
		if goalseek and (followpath or goalpose): 
			arcmove(odomx, odomy, odomth, targetx, targety, targetth, goalth) # blocking
			# nextmove = rospy.get_time() + listentime
			followpath = False
	
	if t - lastpath > 3:
		goalpose = True
	
	rospy.sleep(0.01)
	