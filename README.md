# jumpcutter
Automatically edits videos. Explanation by carykh here: https://www.youtube.com/watch?v=DQ8orIurGxw

## Some heads-up:

It uses Python 3.

It works on Windows 10. (It might work on other OSs too, we just haven't tested it yet.)

This program relies heavily on ffmpeg. It will start subprocesses that call ffmpeg, so be aware of that!
(It makes use of ffprobe too if avaliable)

<s>As the program runs, it saves every frame of the video as an image file in a
temporary folder. If your video is long, this could take a LOT of space.
I have processed 17-minute videos completely fine, but be wary if you're gonna go longer.</s>

<b>Rewrote the program no longer needing to save every frame as an image.</b>