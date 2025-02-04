from contextlib import closing
from PIL import Image
import subprocess
from audiotsm import phasevocoder
from audiotsm.io.wav import WavReader, WavWriter
from scipy.io import wavfile
import numpy as np
import re
import math
import random
import string
from shutil import copyfile, rmtree
import os
import argparse
from pytube import YouTube

def downloadFile(url):
    name = YouTube(url).streams.first().download()
    newname = name.replace(' ','_')
    os.rename(name,newname)
    return newname

def getMaxVolume(s):
    maxv = float(np.max(s))
    minv = float(np.min(s))
    return max(maxv,-minv)

def inputToOutputFilename(filename):
    dotIndex = filename.rfind(".")
    return filename[:dotIndex]+"_ALTERED"+filename[dotIndex:]

parser = argparse.ArgumentParser(description='Modifies a video file to play at different speeds when there is sound vs. silence.')
parser.add_argument('-i', '--input_file', type=str,  help='the video file you want modified')
parser.add_argument('--url', type=str, help='A youtube url to download and process')
parser.add_argument('-o', '--output_file', type=str, default="", help="the output file. (optional. if not included, it'll just modify the input file name)")
parser.add_argument('-st', '--silent_threshold', type=float, default=0.03, help="the volume amount that frames' audio needs to surpass to be consider \"sounded\". It ranges from 0 (silence) to 1 (max volume)")
parser.add_argument('-sd', '--silence_duration', type=int, default=0, help="number of frames of prolonged silence for the duration to be considered silent")
parser.add_argument('-s', '--speed', type=str, default="1:5", help="[speed for sounded segments]:[speed for silent segments] (default: 1.0:5.0)")
parser.add_argument('--sounded_speed', type=float, default=1.00, help="the speed that sounded (spoken) frames should be played at. Typically 1.")
parser.add_argument('--silent_speed', type=float, default=5.00, help="the speed that silent frames should be played at. 999999 for jumpcutting.")
parser.add_argument('-fm', '--frame_margin', type=float, default=1, help="some silent frames adjacent to sounded frames are included to provide context. How many frames on either the side of speech should be included? That's this variable.")
parser.add_argument('-ss', '--section_size', type=float, default=150, help="To speed up processing of larger files the video is split into smaller sections. This is how many sounded or silent chunks are in each section. Larger sections may take longer to process while smaller sections are faster individually but have more overhead to split and recombine")
parser.add_argument('-sr', '--sample_rate', type=float, default=44100, help="sample rate of the input and output videos")
parser.add_argument('-fr', '--frame_rate', type=float, default=30, help="frame rate of the input and output videos. optional... I try to find it out myself, but it doesn't always work.")
parser.add_argument('--simulate', action='store_true', help="does not render video but provides estimated output information")
parser.add_argument('--trim', action='store_true', help="removes the first and last section if it is silent")

args = parser.parse_args()

SECTIONSIZE = args.section_size

SIMULATE = args.simulate
TRIM = args.trim

frameRate = args.frame_rate
SAMPLE_RATE = args.sample_rate
SILENT_THRESHOLD = args.silent_threshold
FRAME_SPREADAGE = args.frame_margin

speed = args.speed.strip().split(':')
if len(speed) != 2:
	print('--speed argument must contain one and only one :')
	exit()
if not speed[0]:
	speed[0] = '1'
if not speed[1]:
	speed[1] = '5'
NEW_SPEED = [float(speed[1]),float(speed[0])]
if NEW_SPEED[0] < 0 or NEW_SPEED[1] < 0:
	print('--speed argument must not be negative')
	exit()
SILENCE_DURATION = args.silence_duration
if args.url != None:
    INPUT_FILE = downloadFile(args.url)
else:
    INPUT_FILE = args.input_file
URL = args.url

assert INPUT_FILE != None , "why u put no input file, that dum"
    
if len(args.output_file) >= 1:
    OUTPUT_FILE = args.output_file
else:
    OUTPUT_FILE = inputToOutputFilename(INPUT_FILE)


output = subprocess.check_output('ffprobe -v quiet -show_streams -select_streams v:0 "{}"'.format(INPUT_FILE))
m = re.search('r_frame_rate=([0-9]+)/([0-9]+)',str(output))
if m is not None:
	frameRate = float(m.group(1))/float(m.group(2))
output = subprocess.check_output('ffprobe -v quiet -show_streams -select_streams a:0 "{}"'.format(INPUT_FILE))
m = re.search('sample_rate=([0-9]+)',str(output))
if m is not None:
	SAMPLE_RATE = float(m.group(1))
m = re.search('bit_rate=([0-9]+)',str(output))
if m is not None:
	BIT_RATE = float(m.group(1))
else:
	BIT_RATE = 160000


tempName = 'temp_{}'.format(''.join(random.choices(string.ascii_letters + string.digits, k=16)))
os.mkdir(tempName)
tempTxt = tempName+'/data.txt'
command = 'ffmpeg -v quiet -stats -i "{input_file}" -ab {bitrate} -ac 2 -ar {samplerate} -vn {temp}/{temp}.wav'.format(input_file=INPUT_FILE, bitrate=BIT_RATE, samplerate=SAMPLE_RATE, temp=tempName)
print('Extracting Audio')
subprocess.call(command, shell=True)


sampleRate, audioData = wavfile.read(tempName+'/'+tempName+'.wav')
audioSampleCount = audioData.shape[0]
maxAudioVolume = getMaxVolume(audioData)
os.remove(tempName+'/'+tempName+'.wav')



samplesPerFrame = sampleRate/frameRate
audioFrameCount = int(math.ceil(audioSampleCount/samplesPerFrame))
hasLoudAudio = np.zeros((audioFrameCount))

for i in range(audioFrameCount):
    start = int(i*samplesPerFrame)
    end = min(int((i+1)*samplesPerFrame),audioSampleCount)
    audiochunks = audioData[start:end]
    maxchunksVolume = float(getMaxVolume(audiochunks))/maxAudioVolume
    if maxchunksVolume >= SILENT_THRESHOLD:
        hasLoudAudio[i] = 1

chunks = [[0,0,0]]
shouldIncludeFrame = np.zeros((audioFrameCount))
for i in range(audioFrameCount):
    start = int(max(0,i-FRAME_SPREADAGE))
    end = int(min(audioFrameCount,i+1+FRAME_SPREADAGE))
    shouldIncludeFrame[i] = np.max(hasLoudAudio[start:end])
    if (i >= 1 and shouldIncludeFrame[i] != shouldIncludeFrame[i-1]): # Did we flip?
        chunks.append([chunks[-1][1],i,shouldIncludeFrame[i-1]])

chunks.append([chunks[-1][1],audioFrameCount,shouldIncludeFrame[i-1]])
chunks = chunks[1:]

if chunks[0][1] - chunks[0][0] < SILENCE_DURATION:
	chunks[0][2] = 1.0
for i in range(len(chunks)-1):
	if len(chunks) <= i:
		break
	if chunks[i][2] == 1.0:
		while i < len(chunks)-1 and (chunks[i+1][1]-chunks[i+1][0] < SILENCE_DURATION or chunks[i+1][2] == 1.0):
			chunks[i][1] = chunks[i+1][1]
			chunks.pop(i+1)

if SIMULATE:
	time = [0,0]
	for chunk in chunks:
		time[int(chunk[2])] = time[int(chunk[2])] + chunk[1] - chunk[0]
	time[0] = time[0]/frameRate
	time[1] = time[1]/frameRate
	print('Time with sound= {h:d}:{m:02d}:{s:02d}'.format(h=int(time[1]/3600), m=int(time[1]/60)%60, s=int(time[1])%60))
	print('Time in silence= {h:d}:{m:02d}:{s:02d}'.format(h=int(time[0]/3600), m=int(time[0]/60)%60, s=int(time[0])%60))
	time[0] = time[0]/NEW_SPEED[0]
	time[1] = time[1]/NEW_SPEED[1]
	print('Adjusted time with sound= {h:d}:{m:02d}:{s:02d}'.format(h=int(time[1]/3600), m=int(time[1]/60)%60, s=int(time[1])%60))
	print('Adjusted time in silence= {h:d}:{m:02d}:{s:02d}'.format(h=int(time[0]/3600), m=int(time[0]/60)%60, s=int(time[0])%60))
	t = time[0] + time[1]
	print('Total output time= {h:d}:{m:02d}:{s:02d}'.format(h=int(t/3600), m=int(t/60)%60, s=int(t)%60))
else:
	fc = 0
	start = 1 if (TRIM and chunks[0][2]==0) else 0
	end = len(chunks) - (1 if (TRIM and chunks[len(chunks)-1][2]==0) else 0)
	
	splitCount = int((end-start+SECTIONSIZE-2)/SECTIONSIZE)
	if splitCount < 2:
		cat = ''
		f = open(tempTxt, 'w')
		for i in range(start, end):
			f.write('[0:v] trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,setpts={arcspeed:.3f}*PTS [v{label}];[0:a] atrim=start_sample={astart}:end_sample={aend},asetpts=PTS-STARTPTS,atempo={speed:.3f} [a{label}];'.format(label=i, start = chunks[i][0], end = chunks[i][1], astart=int((chunks[i][0])*SAMPLE_RATE/frameRate) , aend=int((chunks[i][1])*SAMPLE_RATE/frameRate) , speed = NEW_SPEED[int(chunks[i][2])], arcspeed = 1/NEW_SPEED[int(chunks[i][2])]))
			cat += '[v{0}] [a{0}] '.format(i)
		cat += 'concat=n={}:v=1:a=1 [v] [a]'.format(end-start)
		f.write('{}'.format(cat))
		f.close()

		command = 'ffmpeg -v quiet -stats -i {in_file} -filter_complex_script "{script}" -map [v] -map [a] {out_file}'.format(in_file=INPUT_FILE, out_file=OUTPUT_FILE, script=tempTxt)
		print('Processing 1/1')
		subprocess.call(command, shell=True)
	else:
		splits = []
		j = start
		while j < end:
			j1 = min(j + SECTIONSIZE, end-1)
			splits.append([j,j1])
			command = 'ffmpeg -v quiet -stats -ss {start}s -to {to}s -accurate_seek -i "{in_file}" {out_file}'.format(start=chunks[j][0]/frameRate, to=chunks[j1][1]/frameRate, in_file=INPUT_FILE, out_file='{name}/part{id}.mp4'.format(id=fc,name=tempName))
			print('Splitting {}/{}'.format(fc+1,splitCount))
			subprocess.call(command, shell=True)
			j = j1 + 1
			fc += 1
		
		fc = 0
		for split in splits:
			cat = ''
			start = chunks[split[0]][0]
			f = open(tempTxt, 'w')
			for i in range(split[0],split[1]+1):
				f.write('[0:v] trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,setpts={arcspeed:.3f}*PTS [v{label}];[0:a] atrim=start_sample={astart}:end_sample={aend},asetpts=PTS-STARTPTS,atempo={speed:.3f} [a{label}];'.format(label=i, start = chunks[i][0]-start, end = chunks[i][1]-start, astart=int((chunks[i][0]-start)*SAMPLE_RATE/frameRate) , aend=int((chunks[i][1]-start)*SAMPLE_RATE/frameRate) , speed = NEW_SPEED[int(chunks[i][2])], arcspeed = 1/NEW_SPEED[int(chunks[i][2])]))
				cat += '[v{0}] [a{0}] '.format(i)
			cat += 'concat=n={}:v=1:a=1 [v] [a]'.format(split[1]-split[0]+1)
			f.write(' {}'.format(cat))
			f.close()

			command = 'ffmpeg -v quiet -stats -i {in_file} -filter_complex_script "{script}" -map [v] -map [a] {out_file}'.format(in_file='{name}/part{id}.mp4'.format(id=fc,name=tempName), out_file='{name}/proc{id}.mp4'.format(id=fc,name=tempName), script=tempTxt)
			print('Processing {}/{}'.format(fc+1,len(splits)))
			subprocess.call(command, shell=True)
			os.remove('{name}/part{id}.mp4'.format(id=fc,name=tempName))
			fc += 1
		
		f = open(tempTxt, 'w')
		for k in range(fc):
			if k > 0:
				f.write('\n')
			f.write('file proc{id}.mp4'.format(id=k,name=tempName))
		f.close()
		print('Recombining')
		subprocess.call('ffmpeg -v quiet -stats -f concat -safe 0 -i {input} -vcodec copy -acodec copy "{output}"'.format(output=OUTPUT_FILE, input=tempTxt), shell=True)
		for k in range(fc):
			os.remove('{name}/proc{id}.mp4'.format(id=k,name=tempName))
	os.remove(tempTxt)
os.rmdir(tempName)