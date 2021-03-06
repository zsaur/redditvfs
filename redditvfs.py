#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
This is a reddit virtual filesystem.  Provide a filepath where to mount this
filesystem as an argument and, optionally, an "-f" flag to keep it from
daemonizing.
"""
import errno
import fuse
import stat
import time
import praw
import getpass
import ConfigParser
import sys
import urllib2
import format
import json

fuse.fuse_python_api = (0, 2)

content_stuff = ['thumbnail', 'flat', 'votes', 'content', 'reply',
                 'raw_content', 'link_content']


class redditvfs(fuse.Fuse):
    """
    The filesystem calls which could be utilized in redditvfs are implemented
    here.
    """
    def __init__(self, reddit=None, username=None, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)

        if reddit is None:
            raise Exception('reddit must be set')

    def rmdir(self, path):
        """
        One can run "rmdir" on r/<subreddit>.sub" to unsubscribe from the
        directory.
        """
        if len(path.split('/')) == 3 and reddit.is_logged_in:
            reddit.unsubscribe(path.split('/')[-1:][0])
            return
        else:
            return -errno.ENOSYS

    def mkdir(self, path, mode):
        """
        One can run "mmkdir" on r/<subreddit>.sub" to subscribe to the
        directory.
        """
        if len(path.split('/')) == 3 \
                and path.split('/')[-1:][0][-4:] == '.sub' \
                and reddit.is_logged_in:
            reddit.subscribe(path.split('/')[-1:][0][:-4])
            return
        else:
            return -errno.ENOSYS

    def getattr(self, path):
        """
        Returns stat info for file, such as permissions and access times.
        """

        # default nlink and time info
        st = fuse.Stat()
        st.st_nlink = 2
        st.st_atime = int(time.time())
        st.st_mtime = st.st_atime
        st.st_ctime = st.st_atime

        # everything defaults to being a normal file unless explicitly set
        # otherwise
        st.st_mode = stat.S_IFREG | 0444

        # useful information
        path_split = path.split('/')
        path_len = len(path_split)

        # "." and ".."
        if path_split[-1] == '.' or path_split[-1] == '..':
            # . and ..
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # top-level directories
        if path in ['/', '/u', '/r']:
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # r/*/ - subreddits
        if path_split[1] == 'r' and path_len == 3:
            # check for .sub directories for subscribing
            if reddit.is_logged_in():
                if path.split('/')[-1:][0][-4:] == '.sub':
                    my_subs = [sub.display_name.lower() for sub in
                               reddit.get_my_subreddits()]
                    if (path.split('/')[-1:][0][:-4]).lower() not in my_subs:
                        st = -2
                    else:
                        st.st_mode = stat.S_IFDIR | 0555
                else:
                    st.st_mode = stat.S_IFDIR | 0555
            else:
                # normal subreddit
                st.st_mode = stat.S_IFDIR | 0555
            return st

        # r/*/* - submissions
        if path_split[1] == 'r' and path_len == 4:
            if path_split[-1] == 'post':
                # file to post a submission
                st.st_mode = stat.S_IFREG | 0666
            else:
                # submission
                st.st_mode = stat.S_IFDIR | 0555
            return st

        # r/*/*/[vote, etc] - content stuff in submission
        if (path_split[1] == 'r' and path_len == 5 and path_split[-1] in
                content_stuff):
            st.st_mode = stat.S_IFREG | 0444
            post_id = path_split[3].split(' ')[-1]
            post = reddit.get_submission(submission_id=post_id)
            formatted = ''
            if path_split[-1] == 'content':
                formatted = format.format_sub_content(post)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'votes':
                formatted = str(post.score) + '\n'
            elif path_split[-1] == 'flat':
                formatted = format.format_submission(post)
                formatted = formatted.encode('ascii', 'ignore')
            elif (path_split[-1] == 'thumbnail' and 'thumbnail' in dir(post)
                    and post.thumbnail != '' and post.thumbnail != 'self'
                    and post.thumbnail != 'default'):
                f = urllib2.urlopen(post.thumbnail)
                if f.getcode() == 200:
                    formatted = f.read()
            elif path_split[-1] == 'reply':
                st.st_mode = stat.S_IFREG | 0666
            elif path_split[-1] == 'raw_content' and post.selftext:
                st.st_mode = stat.S_IFREG | 0666
                formatted = post.selftext.encode('ascii', 'ignore')
            elif path_split[-1] == 'raw_content' and post.url:
                st.st_mode = stat.S_IFREG | 0666
                formatted = post.url.encode('ascii', 'ignore')
            elif path_split[-1] == 'link_content' and post.url:
                f = urllib2.urlopen(post.url)
                if f.getcode() == 200:
                    formatted = f.read()
            st.st_size = len(formatted)
            return st

        # r/*/*/** - comment post
        if (path_split[1] == 'r' and path_len > 4 and path_split[-1] not in
                content_stuff and path.split('/')[-1:][0][-1:] != '_'):
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # user link
        if (path_split[1] == 'r' and path_len > 4 and path_split[-1] not in
                content_stuff and path.split('/')[-1:][0][-1:] == '_'):
            st.st_mode = stat.S_IFLNK | 0777
            return st

        # r/*/*/** - comment directory
        if (path_split[1] == 'r' and path_len > 5 and path_split[-1] not in
                content_stuff):
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # r/*/*/** - comment stuff
        if (path_split[1] == 'r' and path_len > 5 and path_split[-1] in
                content_stuff):
            st.st_mode = stat.S_IFREG | 0444
            post = get_comment_obj(path)
            formatted = ''
            if path_split[-1] == 'content':
                formatted = format.format_comment(post, recursive=False)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'votes':
                formatted = str(post.score) + '\n'
            elif path_split[-1] == 'flat':
                formatted = format.format_comment(post, recursive=True)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'reply':
                st.st_mode = stat.S_IFREG | 0666
            elif path_split[-1] == 'raw_content':
                st.st_mode = stat.S_IFREG | 0666
                formatted = post.body.encode('ascii', 'ignore')
            st.st_size = len(formatted)
            return st

        # u/* - user
        if path_split[1] == 'u' and path_len == 3:
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # u/*/* - user stuff (comments, submitted, etc)
        if path_split[1] == 'u' and path_len == 4:
            st.st_mode = stat.S_IFDIR | 0555
            return st

        # u/*/*/* - links (comment, submitted, etc)
        elif (path_split[1] == 'u' and path_len == 5):
            st.st_mode = stat.S_IFLNK | 0777
            return st

    def readlink(self, path):
        """
        Symlinks are used to redirect some references to one thing to a single
        implementation.  The logic to dereference symlinks is here.
        """
        numdots = len(path.split('/'))
        dots = ''
        if path.split('/')[-1:][0][-1:] == '_' and len(path.split('/')) >= 5:
            #if this is a userlink
            numdots -= 2
            while (numdots > 0):
                dots += '../'
                numdots -= 1
            return dots + 'u/' + path.split('/')[-1:][0][11:-1]
        if path.split('/')[1] == 'u' and len(path.split('/')) == 5:
            numdots -= 2
            while (numdots > 0):
                dots += '../'
                numdots -= 1
            comment_id = path.split(' ')[-1]
            sub = str('http://www.reddit.com/comments/'+comment_id)
            sub = reddit.get_submission(sub)
            subname = str(sub.subreddit)
            subid = str(sub.id)
            return str(dots + 'r/' + subname + '/' + subid)

    def readdir(self, path, offset):
        """
        Returns a list of directories in requested path
        """

        # Every directory has '.' and '..'
        yield fuse.Direntry('.')
        yield fuse.Direntry('..')

        # cut-off length on items with id to make things usable for end-user
        pathmax = 50

        path_split = path.split('/')
        path_len = len(path_split)

        if path == '/':
            # top-level directory
            yield fuse.Direntry('u')
            yield fuse.Direntry('r')
        elif path_split[1] == 'r':
            if path_len == 2:
                # if user is logged in, populate with get_my_subreddits
                # otherwise, default to frontpage
                if reddit.is_logged_in():
                    for subreddit in reddit.get_my_subreddits():
                        url_part = subreddit.url.split('/')[2]
                        dirname = sanitize_filepath(url_part)
                        yield fuse.Direntry(dirname)
                else:
                    for subreddit in reddit.get_popular_subreddits():
                        url_part = subreddit.url.split('/')[2]
                        dirname = sanitize_filepath(url_part)
                        yield fuse.Direntry(dirname)
            elif path_len == 3:
                # posts in subreddits
                subreddit = path_split[2]
                for post in reddit.get_subreddit(subreddit).get_hot(limit=20):
                    filename = sanitize_filepath(post.title[0:pathmax]
                                                 + ' ' + post.id)
                    yield fuse.Direntry(filename)
                # write to this to create a new post
                yield fuse.Direntry('post')
            elif path_len == 4:
                # a submission in a subreddit

                post_id = path_split[3].split(' ')[-1]
                post = reddit.get_submission(submission_id=post_id)

                # vote, content, etc
                for file in content_stuff:
                    if file != 'thumbnail' and file != 'link_content':
                        yield fuse.Direntry(file)
                yield fuse.Direntry("_Posted_by_" + str(post.author) + "_")

                if post.thumbnail != "" and post.thumbnail != 'self':
                    # there is link content, maybe a thumbnail
                    if post.thumbnail != 'default':
                        yield fuse.Direntry('thumbnail')
                    yield fuse.Direntry('link_content')

                for comment in post.comments:
                    if 'body' in dir(comment):
                        yield fuse.Direntry(
                            sanitize_filepath(comment.body[0:pathmax]
                                              + ' ' + comment.id))
            elif len(path.split('/')) > 4:
                # a comment or a user

                # Can't find a good way to get a comment from an id, but there
                # is a good way to get a submission from the id and to walk
                # down the tree, so doing that as a work-around.

                comment = get_comment_obj(path)

                for file in content_stuff:
                    if file != 'thumbnail' and file != 'link_content':
                        yield fuse.Direntry(file)
                yield fuse.Direntry('_Posted_by_' + str(comment.author)+'_')

                for reply in comment.replies:
                    if 'body' in dir(reply):
                        yield fuse.Direntry(
                            sanitize_filepath(reply.body[0:pathmax]
                                              + ' ' + reply.id))
        elif path_split[1] == 'u':
            if path_len == 2:
                # if user is logged in, show the user.  Otherwise, this empty
                # doesn't have any values listed.
                if reddit.is_logged_in():
                    yield fuse.Direntry(username)
            if path_len == 3:
                yield fuse.Direntry('Overview')
                yield fuse.Direntry('Submitted')
                yield fuse.Direntry('Comments')
            if path_len == 4:
                user = reddit.get_redditor(path_split[2])
                if path_split[3] == 'Overview':
                    for c in enumerate(user.get_overview(limit=10)):
                        if type(c[1]) == praw.objects.Submission:
                            c_part = c[1].title[0:pathmax] + ' ' + c[1].id
                            yield fuse.Direntry(sanitize_filepath(c_part))
                        if type(c[1]) == praw.objects.Comment:
                            c_part = c[1].body[0:pathmax] + ' ' +\
                                c[1].submission.id
                            yield fuse.Direntry(sanitize_filepath(c_part))
                elif path_split[3] == 'Submitted':
                    for c in enumerate(user.get_submitted(limit=10)):
                        c_part = c[1].title[0:pathmax] + ' ' + c[1].id
                        yield fuse.Direntry(sanitize_filepath(c_part))
                elif path_split[3] == 'Comments':
                    for c in enumerate(user.get_comments(limit=10)):
                        c_part = c[1].body[0:pathmax] + ' ' +\
                            c[1].submission.id
                        yield fuse.Direntry(sanitize_filepath(c_part))

    def read(self, path, size, offset, fh=None):
        """
        Is used to get contents of posts, comments, etc from reddit to the end
        user.
        """
        path_split = path.split('/')
        path_len = len(path_split)

        if path_split[1] == 'r' and path_len == 5:
            # Get the post
            post_id = path_split[3].split(' ')[-1]
            post = reddit.get_submission(submission_id=post_id)

            formatted = ''
            if path_split[-1] == 'content':
                formatted = format.format_sub_content(post)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'votes':
                formatted = str(post.score) + '\n'
            elif path_split[-1] == 'flat':
                formatted = format.format_submission(post)
                formatted = formatted.encode('ascii', 'ignore')
            elif (path_split[-1] == 'thumbnail' and post.thumbnail != '' and
                    post.thumbnail != 'self' and post.thumbnail != 'default'):
                f = urllib2.urlopen(post.thumbnail)
                if f.getcode() == 200:
                    formatted = f.read()
            elif path_split[-1] == 'raw_content' and post.selftext:
                formatted = post.selftext.encode('ascii', 'ignore')
            elif path_split[-1] == 'raw_content' and post.url:
                formatted = post.url.encode('ascii', 'ignore')
            elif path_split[-1] == 'link_content' and post.url:
                f = urllib2.urlopen(post.url)
                if f.getcode() == 200:
                    formatted = f.read()
            return formatted[offset:offset+size]
        elif path_split[1] == 'r' and path_len > 5:
            # Get the comment
            post = get_comment_obj(path)
            if path_split[-1] == 'content':
                formatted = format.format_comment(post, recursive=False)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'votes':
                formatted = str(post.score) + '\n'
            elif path_split[-1] == 'flat':
                formatted = format.format_comment(post, recursive=True)
                formatted = formatted.encode('ascii', 'ignore')
            elif path_split[-1] == 'raw_content':
                formatted = post.body.encode('ascii', 'ignore')
            return formatted[offset:offset+size]

        return -errno.ENOSYS

    def truncate(self, path, len):
        """
        there is no situation where this will actually be used
        """
        pass

    def write(self, path, buf, offset, fh=None):
        """
        Handles voting, content creation, and management. Requires login
        """
        if not reddit.is_logged_in():
            return errno.EACCES

        path_split = path.split('/')
        path_len = len(path_split)

        # Voting
        if path_split[1] == 'r' and path_len >= 5 and\
                path_split[-1] == 'votes':
            # Get the post or comment
            if path_len > 5:
                post = get_comment_obj(path)
            else:
                post_id = path_split[-2].split(' ')[-1]
                post = reddit.get_submission(submission_id=post_id)

            # Determine what type of vote and place the vote
            vote = int(buf)
            if vote == 0:
                post.clear_vote()
            elif vote > 0:
                post.upvote()
            elif vote < 0:
                post.downvote()
            return len(buf)

        # Reply to submission
        if path_split[1] == 'r' and path_len == 5 and\
                path_split[-1] == 'reply':
            post_id = path_split[-2].split(' ')[-1]
            post = reddit.get_submission(submission_id=post_id)
            post.add_comment(buf)
            return len(buf)

        # Reply to comments
        if path_split[1] == 'r' and path_len > 5 and\
                path_split[-1] == 'reply':
            post = get_comment_obj(path)
            post.reply(buf)
            return len(buf)

        # Write a new post
        if path_split[1] == 'r' and path_len == 4 and\
                path_split[-1] == 'post':
            buf_split = buf.split('\n')
            title = buf_split[0]
            if len(buf_split) > 2:
                # Self-post
                text = '\n'.join(buf_split[1:])
                reddit.submit(subreddit=path_split[2], title=title, text=text)
            else:
                # Link
                reddit.submit(subreddit=path_split[2], title=title,
                              url=buf_split[1])
            return len(buf)

        # Edit a post or comment
        if path_split[1] == 'r' and path_len >= 5 and\
                path_split[-1] == 'raw_content':
            # Get the post or comment
            if path_len > 5:
                post = get_comment_obj(path)
            else:
                post_id = path_split[-2].split(' ')[-1]
                post = reddit.get_submission(submission_id=post_id)
            post.edit(buf)
            return len(buf)

        # fake success for editor's backup files
        return len(buf)

    def create(self, path, flags, mode):
        """
        No part of the redditvfs API actually utilizes create() - it is always
        an error.
        """
        return errno.EPERM

    def unlink(self, path):
        """
        Handle deleting posts and comments
        """
        if not reddit.is_logged_in():
            return errno.EACCES

        path_split = path.split('/')
        path_len = len(path_split)

        if path_split[1] == 'r' and path_len >= 5 and\
                path_split[-1] == 'raw_content':
            if path_len > 5:
                post = get_comment_obj(path)
            else:
                post_id = path_split[-2].split(' ')[-1]
                post = reddit.get_submission(submission_id=post_id)
            post.delete()
            return 0
        return errno.EPERM


def sanitize_filepath(path):
    """
    Converts provided path to legal UNIX filepaths.
    """
    # remove illegal and confusing characters
    for char in ['/', '\n', '\0']:
        path = path.replace(char, '_')
    # Direntry() doesn't seem to like non-ascii
    path = path.encode('ascii', 'ignore')
    return path


def get_comment_obj(path):
    """
    given a filesystem path, returns a praw comment object
    """
    # Can't find a good way to get a comment from an id, but there
    # is a good way to get a submission from the id and to walk
    # down the tree, so doing that as a work-around.
    path_split = path.split('/')
    path_len = len(path_split)
    post_id = path_split[3].split(' ')[-1]
    post = reddit.get_submission(submission_id=post_id)
    # quick error check
    if len(post.comments) == 0:
        return -errno.ENOENT
    for comment in post.comments:
        if comment.id == path_split[4].split(' ')[-1]:
            break
    level = 4
    if path_split[-1] in content_stuff:
        adjust = 2
    else:
        adjust = 1
    while level < path_len - adjust:
        level += 1
        for comment in comment.replies:
            if comment.id == path_split[level].split(' ')[-1]:
                break
    return comment


def login_get_username(config):
    """
    returns the username of the user to login
    """
    try:
        username = config.get('login', 'username')
    except Exception, e:
        # Prompt for username
        username = raw_input("Username: ")
        pass
    return username


def login_get_password(config):
    """
    returns the password of the user to login
    """
    try:
        password = config.get('login', 'password')
    except Exception, e:
        # Prompt for password
        password = getpass.getpass()
        pass
    return password


if __name__ == '__main__':
    # Create a reddit object from praw
    reddit = praw.Reddit(user_agent='redditvfs')

    # Login only if a configuration file is present
    if '-c' in sys.argv:
        # Remove '-c' from sys.argv
        sys.argv.remove('-c')

        # User wants to use the config file, create the parser
        config = ConfigParser.RawConfigParser(allow_no_value=True)

        # Check for default login
        try:
            config.read('~/.redditvfs.conf')
        except Exception, e:
            pass
        finally:
            username = login_get_username(config=config)
            password = login_get_password(config=config)
            try:
                reddit.login(username=username, password=password)
                print 'Logged in as: ' + username
            except Exception, e:
                print e
                print 'Failed to login'
    else:
        username = None

    fs = redditvfs(reddit=reddit, username=username, dash_s_do='setsingle')
    fs.parse(errex=1)
    fs.main()
