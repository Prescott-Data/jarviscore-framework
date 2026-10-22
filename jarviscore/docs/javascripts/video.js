/* Click-to-play YouTube. The page ships a thumbnail link; YouTube loads only
   when someone presses play, so pages stay fast and nothing is fetched from
   YouTube before then. Without JavaScript the link opens the video on YouTube. */
document.addEventListener('click', function (event) {
  var poster = event.target.closest('.jc-video .jc-video-poster');
  if (!poster) return;
  var box = poster.closest('.jc-video');
  var id = box && box.getAttribute('data-yt');
  if (!id || !/^[\w-]{11}$/.test(id)) return;
  event.preventDefault();
  var frame = document.createElement('iframe');
  frame.src = 'https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1&rel=0&modestbranding=1';
  frame.title = box.getAttribute('data-title') || 'Video';
  frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
  frame.allowFullscreen = true;
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  poster.replaceWith(frame);
  box.classList.add('is-playing');
});
