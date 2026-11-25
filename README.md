# Golden Hour Ride

A proof-of-concept indoor cycling ride that runs in the browser (Three.js, one `index.html`).

Live: https://golden-hour-ride.space.fast/ · Leckhampton loop: https://golden-hour-ride.space.fast/?course=leckhampton · Gempen loop: https://golden-hour-ride.space.fast/?course=basel

## What's in it

- A landing page at the plain address: the settings (weather, how much of each hill the trainer gives you, maximum heart rate, Christmas, scenery mode), kept in the browser, and the list of courses. Choosing a course starts the ride; the Course button goes back to the list. Links with `?course=` skip the landing page.
- Four courses: an invented mountain valley; a real 11.9 km Leckhampton loop built from Environment Agency lidar, dressed as the 19th-century hill (sheep, hay stooks, quarry smoke); and a real 27 km Gempen loop above Basel (`?course=basel`), shown as it is today: the ground is swisstopo's aerial photo, and every tree near the road stands where the laser survey found it, at its measured height, with the darker crowns drawn as spruce and fir. There are no buildings: the builder can draw them from swisstopo's 3D models (`BUILDINGS = True` in `tools/build_course_world.py`), but they are off. Gempen runs from St. Jakob through Dornach, up the Gempenstrasse (about 400 m of climbing, up to 13 %), on to Schönmatt and down to Arlesheim; the ride starts in Dornach, just before the climb. And Muttenz – Gempen (`?course=muttenz`), a real ride recorded on Strava: 27.9 km and 580 m of climbing from Birsfelden through Muttenz, up past Wartenberg and Sulz to Schartenflue and the Gempen plateau, and down through Arlesheim and Münchenstein, in the same present-day dressing; the ride starts in Muttenz, just before the Wartenberg climb. A course can come from a GPX file like this one (`tools/routes/`) or from router waypoints; see `COURSES` in `tools/build_course.py`. 
- Four looks: Golden, Overcast, Rain and Mist. Buttons at the top, keys 1–4, or by voice.
- A course map in the bottom right corner: the whole road from above, north up, with climbs in amber (deeper for steeper), a square where the ride began and an arrow for where you are and which way you are heading. Under it, an elevation profile of the whole course, coloured the same way, with a marker and your current height; the part already ridden is dimmed. Hide info hides both.
- Skip forward and back 250 m with the arrow keys.
- Hide everything on screen for a clean view: the Hide info button, the H key, or say "hide". Press H, click, or say "show" to bring it back.
- Power from a slider, or from a Bluetooth trainer (Chrome or Edge). If the trainer supports resistance control (FTMS), the ride also sends it the road gradient, so climbs feel harder; the button shows "Trainer: power and gradient" or "Trainer: power only". The trainer feels half the road gradient by default; the − and + buttons beside the trainer button change that in steps of 10 %, from off to the full gradient, and the choice is kept in the browser (`?hills=` sets it for one visit). With voice on, say "easier" or "harder" to move it by 20 %, "flat" for off, or "full" for all of it. The last trainer is remembered: the button reads "Reconnect trainer" and rejoins it without the browser's device list where Chrome allows that, and a dropped connection is retried automatically.
- Heart rate from a Bluetooth strap or watch that broadcasts it (Chrome or Edge): the Connect HR button, separate from the trainer. Once connected, bpm shows in the HUD and on the head unit, and each ride in the log keeps its average heart rate. The strap is remembered and reconnected like the trainer. The number is coloured by zone (Z1 Recovery under 60 % of maximum heart rate, Z2 Endurance 60–70 %, Z3 Tempo 70–80 %, Z4 Threshold 80–90 %, Z5 Max above), and each ride in the log shows a bar of its time in each zone. The edge of the screen glows in the zone colour and pulses with each heartbeat, stronger in the higher zones; it fades away when no heart rate is coming in, and stays on when the info is hidden. Maximum heart rate is 190 until you change it with the Max HR button or `?maxhr=`; it is kept in the browser.
- ERG mode: the ERG button beside Hills makes a smart trainer (FTMS) hold a set power, whatever your cadence and whatever the road does; − and + change it by 5 W, the ↑ ↓ keys by 10 W, and with voice on "ERG", "ERG off", "easier" and "harder" (10 W). The speed on screen still follows the road. It is kept in the browser, can be set on the landing page, and `?erg=200` turns it on at 200 W for one visit. Without a trainer the ride just holds that power.
- Workouts: pick one on the landing page, with your FTP (the power you could hold for about an hour). 88 are built in, eleven of each kind (recovery, endurance, tempo, sweet spot, threshold, over-unders, VO2max and VO2max short intervals), mostly 45 to 120 minutes. Choose a workout opens them as cards, each with a chart of the power it asks for over time (the dashed line is FTP), filtered by kind and sorted by length. Each step is a share of FTP, so the trainer is put in ERG and walked through them; a panel shows the step, the time left in it, what comes next and the whole workout as a chart. − and + (or ↑ ↓) make the whole workout 5 % easier or harder; Skip step and End workout do what they say. `?workout=vo2&ftp=250` picks one from the address. Without a trainer the ride holds each step's power.
- Descents count half in the speed model and the rider brakes above 54 km/h, so downhill speed stays sensible.

## Run it locally

```bash
python3 -m http.server 8791
```

Then open http://localhost:8791/.

## Layout

- `index.html` – the whole ride.
- `assets/` – textures and course data. `textures.js` is an embedded copy of the textures, used only when the page is opened straight from disk.
- `tools/` – scripts that build the course data. `build_leckhampton.py` and `build_leckhampton_osm.py` build Leckhampton. `build_course.py <course>` builds a Swiss course's road and terrain, then `build_course_world.py <course>` its present-day world (`assets/<course>_ortho.jpg` and `assets/<course>_world.js`); they share `swisstopo.py`, need `pip3 install tifffile imagecodecs numpy pillow`, and keep their downloads in `tools/.cache/` (the world build reads about 2.5 GB the first time, but keeps only what it uses). `build_course_osm.py` is the OpenStreetMap version, for a Swiss course without the world files.
- `deploy.sh` – publishes to Spacefast.

## Credits

- Textures: Poly Haven (CC0).
- Terrain: Environment Agency LiDAR Composite DTM, Open Government Licence v3.0 (Leckhampton); swissALTI3D © swisstopo, open data (Gempen).
- Gempen aerial photo, buildings and trees: SWISSIMAGE, swissBUILDINGS3D 3.0 and swissSURFACE3D © swisstopo, open data.
- Roads, woodland and field boundaries: © OpenStreetMap contributors, ODbL.
- 3D engine: Three.js (MIT), loaded from jsDelivr.

## Licence

The code is released under the MIT licence: see `LICENSE`. Use it, change it, build your own ride.

The MIT licence covers the code only. The course data in `assets/leckhampton*.js`, `assets/basel*.js` and `assets/basel_ortho.jpg` is derived from the sources credited above and stays under their terms: the Open Government Licence v3.0 for the Leckhampton terrain, swisstopo's open-data terms (credit "© swisstopo") for everything on Gempen (terrain, photo, buildings and trees), and the ODbL for the OpenStreetMap data. If you share or adapt that data, keep those credits.
