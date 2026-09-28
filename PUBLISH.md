# Publishing this

Notes for me, not for players.

## 0. Fix the commit author

This machine has no global git identity, so the first commits were made with a placeholder address.
Set your real one and rewrite the history, otherwise GitHub will not link the commits to your
account:

```sh
git config --global user.name "Justin Vijfschaft"
git config --global user.email "you@example.com"
git rebase --root --exec 'git commit --amend --reset-author --no-edit'
```

## 1. Fill in the GitHub account

`README.md` and `install.sh` both carry `OWNER` as a placeholder. Replace it with your account
name, then commit:

```sh
sed -i 's/OWNER/your-github-user/g' README.md install.sh
git add -A && git commit -m "Point the install URLs at the repository"
```

## 2. Create the repository

Call it `flappy-terminal` so the raw URLs in the README resolve. Another name is fine as long as
`FLAPPY_REPO` in `install.sh` and the URLs in `README.md` match it.

```sh
git remote add origin git@github.com:your-github-user/flappy-terminal.git
git push -u origin main
```

## 3. Check the install path end to end

Once the default branch is pushed, from a clean machine or a container:

```sh
curl -fsSL https://raw.githubusercontent.com/your-github-user/flappy-terminal/main/install.sh | sh
flappy --version
```

The installer refuses a download that fails `--selftest`, so a broken commit on `main` cannot
reach anyone's PATH.

To rehearse that without pushing anything, serve this directory and point the installer at it:

```sh
python3 -m http.server 8731 --bind 127.0.0.1 &
FLAPPY_URL=http://127.0.0.1:8731/flappy.py FLAPPY_BIN=/tmp/bin sh install.sh
```

## 4. Before each release

```sh
python3 flappy.py --selftest
sh -n install.sh
```

Bump `__version__` in `flappy.py`, then tag:

```sh
git tag -a v1.3.0 -m "v1.3.0"
git push --tags
```

Anyone pinning a version installs with `FLAPPY_REF=v1.3.0`.

## Note on the local symlink

`~/.local/bin/flappy` is a symlink to `flappy.py` in this directory, so edits here take effect
immediately. Running `install.sh` without `FLAPPY_BIN` replaces that symlink with a downloaded
copy. To get the symlink back:

```sh
ln -sfn "$PWD/flappy.py" ~/.local/bin/flappy
```
