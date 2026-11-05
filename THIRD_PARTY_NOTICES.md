# Third-party components

The original private-desktop gateway, launcher, demo and tests are MIT licensed.

The sandbox build downloads **agent-desktop 1.1.0**, maintained by Vercel Labs,
from https://github.com/vercel-labs/agent-desktop/releases/tag/v1.1.0.
agent-desktop is Apache-2.0 licensed. Its license is included at
`src/private_desktop/assets/AGENT_DESKTOP_LICENSE` and copied into the built image
at `/usr/share/doc/agent-desktop/LICENSE`.

The Ubuntu base image and packages installed using apt retain their respective
licenses. Package copyright and license records are available in the image under
`/usr/share/doc/`. Docker Desktop and Python are separately installed prerequisites
and are not distributed by this project.
