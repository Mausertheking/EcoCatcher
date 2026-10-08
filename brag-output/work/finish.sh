set -e
cd /home/user/EcoCatcher/brag-output
# mux picture + score
ffmpeg -y -loglevel error -i work/video-silent.mp4 -i work/score.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest work/brag-raw.mp4
# poster: settled masthead frame, "Baku, Azerbaijan" underlined
ffmpeg -y -loglevel error -ss 6.0 -i work/brag-raw.mp4 -frames:v 1 -q:v 2 brag.jpg
# bake the poster in as frame 0 (replace, keep timing)
ffmpeg -y -loglevel error -i work/brag-raw.mp4 -i brag.jpg \
  -filter_complex "[0:v][1:v]overlay=0:0:enable='eq(n,0)'[v]" \
  -map "[v]" -map "0:a?" -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p \
  -c:a copy -movflags +faststart brag.mp4
ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames -of compact brag.mp4
