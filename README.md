# Instagram Reels Auto Poster (10 accounts, har 12 ghante, 2 reels)

## Folder structure
queue/
  001/video.mp4 + caption.txt
  002/video.mp4 + caption.txt
  003/ ...
Har reel ka alag folder (number order me post hota hai).
Har 12 ghante par agle 2 reels, sabhi 10 accounts par, same caption ke sath.

## GitHub Secrets / Variables
- Secret USER_TOKEN = long-lived user token (Graph API Explorer + Access Token Debugger se "Extend")
  Script khud pages aur Instagram accounts nikal leta hai.
- (Optional) Variable ONLY_ACCOUNTS = comma separated instagram usernames / page names (agar 10 se zyada hon)
- (Optional alternative) Secret ACCOUNTS_JSON (format: accounts.example.json) - ho to wahi use hoga

## Important
- Repo PUBLIC hona chahiye (Instagram ko video URL public chahiye).
- Video: MP4, 9:16, 3-90 sec, 100MB se kam.
