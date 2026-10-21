// Open a file (the HTML report) in the default program: browser for .html. Never throws; it only logs.
import { spawn } from 'node:child_process';

export function openCommand(
  file: string,
  platform: NodeJS.Platform = process.platform,
): {
  cmd: string;
  args: string[];
  verbatim: boolean;
} {
  // `start` is a cmd built-in; the empty "" is the window title, so a path with spaces still works.
  if (platform === 'win32')
    return { cmd: 'cmd', args: ['/c', 'start', '""', `"${file}"`], verbatim: true };
  if (platform === 'darwin') return { cmd: 'open', args: [file], verbatim: false };
  return { cmd: 'xdg-open', args: [file], verbatim: false };
}

export function openFile(file: string, log: (l: string) => void = console.log): void {
  const { cmd, args, verbatim } = openCommand(file);
  try {
    const child = spawn(cmd, args, {
      detached: true,
      stdio: 'ignore',
      windowsVerbatimArguments: verbatim,
    });
    child.on('error', () => log(`[c3] could not open the report; open it by hand: ${file}`));
    child.unref();
  } catch {
    log(`[c3] could not open the report; open it by hand: ${file}`);
  }
}
