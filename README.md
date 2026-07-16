# RemoteSubl

RemoteSubl starts as a fork of [rsub](https://github.com/henrikpersson/rsub) to
bring `rmate` feature of TextMate to Sublime Text. It transfers files to be
edited from remote server using SSH port forward and transfers the files back
when they are saved.

Comparing to rsub, the followings are enhanced:

- support multiple files via `rmate foo bar`.
- use the same view when opening the same file twice.
- notify when connection lost.
- resume previous connection when it was lost.
- better status bar messages when saving file and when encountering errors.
- bring up Sublime Text on different platforms.
- ability to set a custom color scheme.

Why a new fork? It seems that the author of rsub is not actively maintaining
that package.

# Installation

Before installing on your remote server, RemoteSubl can easily be installed
using [Package Control](https://packagecontrol.io).

Once you have that completed, open up Sublime Text *(the rest won't work unless
you do)*.

On the remote server, we need to install
[rmate](https://github.com/aurora/rmate) (this one is the bash version). You
don't have to install it if you have been using `rmate` with TextMate or other
editors. It is just the same executable. If not, it (the bash version) can be
installed by running this script (assuming you have the right permission),

```bash
curl -o /usr/local/bin/rmate https://raw.githubusercontent.com/aurora/rmate/master/rmate
sudo chmod +x /usr/local/bin/rmate
```

You can also rename the command to `rsubl`

```
mv /usr/local/bin/rmate /usr/local/bin/rsubl
```

If your remote system does not have `bash` (so what else does it have?), there
are different versions of `rmate` to choose from:

- The official ruby version: https://github.com/textmate/rmate
- A bash version: https://github.com/aurora/rmate
- A perl version: https://github.com/davidolrik/rmate-perl
- A python version: https://github.com/sclukey/rmate-python
- A nim version: https://github.com/aurora/rmate-nim
- A C version: https://github.com/hanklords/rmate.c
- A node.js version: https://github.com/jrnewell/jmate


---

# Usage

Open an ssh connection to the remote server with remote port forwarded. It can
be done by executing the following command on your local machine:

```bash
ssh -R 52698:127.0.0.1:52698 user@example.com


> [!WARNING]
> **Avoid using `localhost` in your port forwarding setup.**
> On many systems, `localhost` resolves to the IPv6 loopback (`::1`), while the 
> local Sublime Text helper server binds strictly to IPv4 (`127.0.0.1`). This 
> mismatch will cause `rmate` to silently fail and drop the connection with a 
> **SIGPIPE (exit code 141)**. Always use `127.0.0.1` explicitly.

After running the server, you can just open the file by typing the following
command in your remote system's terminal:

```bash 
rmate test.txt
```

(*NOTE:* you need to have opened Sublime Text on your local machine. 
*If not* you get this error: `connect_to 127.0.0.1 port 52698: failed.` on your
 server)

... or if you renamed it to rsubl then ...

```bash 
rsubl test.txt
```

If everything has been setup correctly, you should be able to see the opening
file in Sublime Text.

## SSH config

It could be tedious to type `-R 52698:127.0.0.1:52698` everytime you ssh. To
make your life easier, add the following to `~/.ssh/config`,

```text 
Host example.com
    RemoteForward 52698 127.0.0.1:52698
    User user
```

From now on, you only have to do `ssh example.com`.

### PuTTY config

Alternatively, if you're using PuTTY as your SSH client, before you connect to
your host:

1. Navigate to `Connection` > `SSH` > `Tunnels` in the left-hand navigation pane
1. In the `Add new forwarded port:` section, add `52698` to `Source port` text field
1. Then add `127.0.0.1:52698` in the `Destination` text field
1. Select `Remote` checkbox instead of `Local`
1. Click `Add` to add your forwarding information to the `Forwarded ports:` list
1. Save your settings if you'd like, and then connect to your remote host
