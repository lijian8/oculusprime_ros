#!/usr/bin/env python

import rospy, tf
import socketclient
from nav_msgs.msg import Odometry
import math
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseStamped #, PoseWithCovarianceStamped
from actionlib_msgs.msg import GoalStatusArray

listentime = 0.9 # magic constant, seconds
nextmove = 0
odomx = 0
odomy = 0
odomth = 0
targetx = 0	
targety = 0
targetth = 0
followpath = False
goalth = 0 
minturn = math.radians(6) # 0.21 minimum for pwm 255
lastpath = 0
goalpose = False
goalseek = False
linearspeed = 150
secondspermeter = 3.2 #float
turnspeed = 100
secondspertwopi = 3.8
initth = 0
#initgoalth = 0
tfth = 0
gbpathx = 0
gbpathy = 0
gbpathth = 0
initturn = False

def pathCallback(data):
	global targetx, targety, targetth, followpath, lastpath, goalpose
		
	lastpath = rospy.get_time()
	goalpose = False
	followpath = True
	p = data.poses[len(data.poses)-1] # get latest pose
	targetx = p.pose.position.x
	targety = p.pose.position.y
	quaternion = ( p.pose.orientation.x, p.pose.orientation.y,
	p.pose.orientation.z, p.pose.orientation.w )
	targetth = tf.transformations.euler_from_quaternion(quaternion)[2]
	
def globalPathCallback(data):
	global gbpathx, gbpathy, gbpathth
	n = len(data.poses)
	if n > 0:
		p = data.poses[int(n*0.1)] #[len(data.poses)-1] # choose pose 10% along path
		gbpathx = p.pose.position.x
		gbpathy = p.pose.position.y
		quaternion = ( p.pose.orientation.x, p.pose.orientation.y,
		p.pose.orientation.z, p.pose.orientation.w )
		gbpathth = tf.transformations.euler_from_quaternion(quaternion)[2]

def odomCallback(data):
	global odomx, odomy, odomth
	odomx = data.pose.pose.position.x
	odomy = data.pose.pose.position.y
	quaternion = ( data.pose.pose.orientation.x, data.pose.pose.orientation.y,
	data.pose.pose.orientation.z, data.pose.pose.orientation.w )
	odomth = tf.transformations.euler_from_quaternion(quaternion)[2]
	
def goalCallback(data):
	global goalth, followpath, lastpath, goalpose
	global odomx, odomy, odomth, targetx, targety, targetth, tfth
	global gbpathx, gbpathy, gbpathth, initturn
	
	# set goal angle
	quaternion = ( data.pose.orientation.x, data.pose.orientation.y,
	data.pose.orientation.z, data.pose.orientation.w )
	goalth = tf.transformations.euler_from_quaternion(quaternion)[2]

	# turn towards global path before doing anything
	goalpose = False	
	initturn = True
	gbpathx = None
	t = rospy.get_time()
	lastpath = t
	while gbpathx == None and rospy.get_time() < t + 2.0: # wait for global path
		pass
	
	dx = gbpathx - odomx
	dy = gbpathy - odomy	
	distance = math.sqrt( pow(dx,2) + pow(dy,2) )
	if distance > 0:
		gbth = math.acos(dx/distance)
		if dy <0:
			gbth = -gbth
		# gbth += tfth
		move(0, 0, odomth, 0, 0, gbth, gbth)  # turn only 
		rospy.sleep(1) # led amcl settle
	initturn = False

	lastpath = rospy.get_time()
	followpath = False
	
def goalStatusCallback(data):
	global goalseek
	goalseek = False
	if len(data.status_list) == 0:
		return
	status = data.status_list[len(data.status_list)-1] # get latest status
	if status.status == 1:
		goalseek = True

def move(ox, oy, oth, tx, ty, tth, gth):
	global followpath, goalpose, tfth

	# print "odom: "+str(ox)+", "+str(oy)+", "+str(oth)
	# print "target: "+str(tx)+", "+str(ty)+", "+str(tth)
	
	distance = 0
	if followpath:
		dx = tx - ox
		dy = ty - oy	
		distance = math.sqrt( pow(dx,2) + pow(dy,2) )
	
	if distance > 0:
		th = math.acos(dx/distance)
		if dy <0:
			th = -th
	elif goalpose:
		th = gth - tfth
	else:
		th = tth
	
	dth = th - oth
	if dth > math.pi:
		dth = -math.pi*2 + dth
	elif dth < -math.pi:
		dth = math.pi*2 + dth
		
	# force minimums	
	if distance > 0 and distance < 0.05:
		distance = 0.05

	# supposed to reduce zig zagging
	if dth < minturn*0.3 and dth > -minturn*0.3:
		dth = 0
	elif dth >= minturn*0.3 and dth < minturn:
		dth = minturn
	elif dth <= -minturn*0.3 and dth > -minturn:
		dth = -minturn


	if dth > 0:
		socketclient.sendString("speed "+str(turnspeed) )
		socketclient.sendString("move left")
		rospy.sleep(dth/(2.0*math.pi) * secondspertwopi)
		socketclient.sendString("move stop")
		socketclient.waitForReplySearch("<state> direction stop")
	elif dth < 0:
		socketclient.sendString("speed "+str(turnspeed) )
		socketclient.sendString("move right")
		rospy.sleep(-dth/(2.0*math.pi) * secondspertwopi)
		socketclient.sendString("move stop")
		socketclient.waitForReplySearch("<state> direction stop")

	if distance > 0:
		socketclient.sendString("speed "+str(linearspeed) )
		socketclient.sendString("move forward")
		rospy.sleep(distance*secondspermeter)
		socketclient.sendString("move stop")
		socketclient.waitForReplySearch("<state> direction stop")
	
def cleanup():
	socketclient.sendString("odometrystop")
	socketclient.sendString("state stopbetweenmoves false")
	socketclient.sendString("move stop")


# MAIN

rospy.init_node('base_controller', anonymous=False)
rospy.Subscriber("move_base/DWAPlannerROS/local_plan", Path, pathCallback)
rospy.Subscriber("odom", Odometry, odomCallback)
rospy.Subscriber("move_base_simple/goal", PoseStamped, goalCallback)
rospy.Subscriber("move_base/status", GoalStatusArray, goalStatusCallback)
rospy.Subscriber("move_base/DWAPlannerROS/global_plan", Path, globalPathCallback)
rospy.on_shutdown(cleanup)
listener = tf.TransformListener()

while not rospy.is_shutdown():
	t = rospy.get_time()
	
	if t >= nextmove:
		nextmove = t + listentime
		if goalseek and not initturn:
			move(odomx, odomy, odomth, targetx, targety, targetth, goalth)
			followpath = False
	
	if t - lastpath > 3:
		goalpose = True
	
	try:
		(trans,rot) = listener.lookupTransform('/map', '/odom', rospy.Time(0))
	except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
		continue		
	quaternion = (rot[0], rot[1], rot[2], rot[3])
	tfth = tf.transformations.euler_from_quaternion(quaternion)[2]
		
cleanup()