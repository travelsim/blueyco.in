#!/bin/bash
# Set up git credentials for push
cd /Users/jameslove/bluey-coin-tracker

# Store token in git credential store
echo "url=https://travelsim@github.com/travelsim/blueyco.in.git" | git credential-store --file ~/.git-credentials-store store

# Use the credential store
git config --global credential.helper 'store --file ~/.git-credentials-store'

# Push
git push origin main
