with open('browser_controller.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The new robust ad-skipper function implementation
new_skipper = '''async def _auto_skip_ads(page):
    while True:
        try:
            await page.evaluate(\"\"\"() => {
                // 1. Target all known variations of skip buttons
                const skipBtns = document.querySelectorAll(
                    .ytp-ad-skip-button, 
                    .ytp-skip-ad-button, 
                    button.ytp-ad-skip-button-modern, 
                    .ytp-ad-overlay-close-button,
                    .video-ads .ytp-ad-button-icon
                );
                skipBtns.forEach(btn => {
                    if (btn) {
                        btn.click();
                        btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    }
                });

                // 2. Comprehensive ad state detection
                const player = document.querySelector('.html5-video-player');
                const video = document.querySelector('video');
                
                if (player && video) {
                    const isAdPlaying = player.classList.contains('ad-showing') || 
                                        player.classList.contains('ad-interrupting') ||
                                        document.querySelector('.ad-showing') !== null;

                    if (isAdPlaying) {
                        video.muted = true;
                        video.playbackRate = 16.0;
                        
                        if (video.seekable && video.seekable.length > 0) {
                            video.currentTime = video.seekable.end(0);
                        } else if (Number.isFinite(video.duration)) {
                            video.currentTime = video.duration;
                        }
                    } else {
                        if (video.playbackRate === 16.0) {
                            video.playbackRate = 1.0;
                            video.muted = false;
                        }
                    }
                }
            }\"\"\")
        except Exception:
            pass
        await asyncio.sleep(0.1)'''

if 'async def _auto_skip_ads(' in content:
    # Replace the old _auto_skip_ads function up to the next function definition
    parts = content.split('async def _auto_skip_ads(')
    prefix = parts[0]
    suffix_parts = parts[1].split('async def ')
    suffix = 'async def ' + ''.join(suffix_parts[1:]) if len(suffix_parts) > 1 else ''
    
    updated_content = prefix + new_skipper + '\n\n' + suffix
    with open('browser_controller.py', 'w', encoding='utf-8') as f:
        f.write(updated_content)
    print("browser_controller.py updated successfully!")
else:
    print("Could not find _auto_skip_ads in browser_controller.py")
