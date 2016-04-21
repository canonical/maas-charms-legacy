import argparse
import os

from django.contrib.auth.models import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old-username', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--email', required=True)

    args = parser.parse_args()
    user = User.objects.get(username=args.old_username)
    user.username = args.username
    user.email = args.email
    user.set_password(args.password)
    user.save()


if __name__ == "__main__":
    main()
