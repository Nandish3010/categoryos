import { Config } from '@remotion/cli/config';

// Use the system Google Chrome so no browser download is needed.
Config.setBrowserExecutable(process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setConcurrency(4);
