"""The README's video card: the film's own thumbnail with a play control and its length.

GitHub cannot embed YouTube, so the README links this image to the film.
Writes video-card.html; render it at 1280x720 with Chromium and save as JPEG.
"""
VIDEO, LENGTH = "4IOpKZgjXIw", "2:07"
html = f"""<!doctype html><html><body style="margin:0">
<div style="position:relative;width:1280px;height:720px;overflow:hidden;font-family:'Avenir Next','Helvetica Neue',Arial,sans-serif">
  <img src="https://i.ytimg.com/vi/{VIDEO}/maxresdefault.jpg" style="width:100%;height:100%;object-fit:cover;display:block">
  <div style="position:absolute;left:50%;top:69%;transform:translate(-50%,-50%);width:120px;height:84px;border-radius:22px;background:rgba(0,0,0,.72)">
    <div style="position:absolute;left:47px;top:24px;border-style:solid;border-width:18px 0 18px 32px;border-color:transparent transparent transparent #fff"></div>
  </div>
  <div style="position:absolute;right:28px;bottom:26px;padding:6px 12px;border-radius:8px;background:rgba(0,0,0,.78);color:#fff;font-size:24px;font-weight:600">{LENGTH}</div>
</div></body></html>"""
open("video-card.html", "w").write(html)
