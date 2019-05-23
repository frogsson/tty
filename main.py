#!/usr/bin/env python

import urllib.request
import urllib.parse
import threading
import logging
import queue
import sys
import os
import argparser
import tistory_extractor as tistory


SPECIAL_CHARS = r'!\"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
CONTENT_TYPES = ["image/jpeg", "image/png", "image/gif, image/webp"]
IMG_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'webp']


class E:
    pic_q = queue.Queue()
    page_q = queue.Queue()
    lock = threading.Lock()

    imgs_downloaded = 0
    total_img_found = 0
    already_found = 0

    error_links = []


def run(args):
    settings = argparser.parse(args[1:])
    E.title_filter_words = settings.get_title_filter()
    E.debug = settings.debug_status()
    E.organize = settings.organize_status()

    E.url = settings.get_url()
    E.urlparse = urllib.parse.urlparse(E.url)

    if E.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

    # logger = logging.getLogger('main')
    logging.debug('%s', E.url)

    # Parse pages for images
    if settings.page_status():
        if not E.url.endswith("/"):
            E.url = E.url + "/"
        for page in settings.get_pages():
            E.page_q.put(page)
        print("Fetching source for:")
        start_threads(settings.get_threads(), work_page)
    else:
        print("Fetching page source...")
        html = fetch(E.url)
        if html:
            parse_page(E.url, html, '')
        else:
            sys.exit()
    E.total_img_found = E.pic_q.qsize()

    # Starts the download
    print("\nStarting download:")
    start_threads(settings.get_threads(), DL)

    # Final report
    print("\nDone!")
    print("Found:", E.total_img_found)
    if E.imgs_downloaded > 0:
        print("Saved:", E.imgs_downloaded)
    if E.already_found > 0:
        print("Already saved:", E.already_found)

    if E.error_links:
        print('Errors: %s' % len(E.error_links))
    if E.error_links:
        print("\nCould not download:")
        for url in E.error_links:
            print(url)


def start_threads(t, _target):
    img_threads = [threading.Thread(target=_target) for i in range(int(t))]

    for thread in img_threads:
        thread.start()

    for thread in img_threads:
        thread.join()


def DL():
    while E.pic_q.qsize() > 0:
        data = E.pic_q.get()
        url = data["url"]
        title = data["title"]
        page = " -page /", data["page"] if data["page"] is not None else ""

        # fetch image content, returns None if error
        img_content = fetch(url, page=page)

        if img_content is None:
            continue

        img_info = img_content.info()

        # Filter out files under 10kb
        if img_info["Content-Length"] and int(img_info["Content-Length"]) < 10000:
            with E.lock:
                E.total_img_found -= 1
            continue

        # Filter out non jpg/gif/png
        if not img_info["Content-Type"] or img_info["Content-Type"] not in CONTENT_TYPES:
            with E.lock:
                E.total_img_found -= 1
            continue

        print(url)
        with E.lock:
            img_path = get_img_path(url, title, img_info, filename=data['filename'])
            if E.debug:
                continue
            if img_path is not None:
                with open(img_path, 'wb') as f:
                    f.write(img_content.read())
                E.imgs_downloaded += 1
            else:
                E.already_found += 1


def get_img_path(url, folder_name, img_info, filename):
    if img_info['Content-Disposition'] and not filename:
        # filename fallback 1
        filename = img_info['Content-Disposition']
        if "filename*=UTF-8" in filename:
            filename = filename.split("filename*=UTF-8''")[1]
            filename = filename.rsplit(".", 1)[0]
        else:
            filename = filename.split('"')[1]
        filename = urllib.request.url2pathname(filename)

    if not filename:
        # filename fallback 2
        filename = url.split('/')[-1]
        filename = filename.strip('/')

    if '.' in filename and filename.rsplit('.', 1)[1] not in IMG_EXTS:
        extension = "." + img_info["Content-Type"].split("/")[1]
        extension = extension.replace("jpeg", "jpg")
        filename = filename + extension

    filename = filename.strip()

    if E.organize:
        if folder_name is None:
            folder_name = "Untitled"
        for char in SPECIAL_CHARS:
            folder_name = folder_name.replace(char, "")
        folder_name = folder_name.strip()
        img_path = os.path.join(folder_name, filename)
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
    else:
        img_path = filename.strip()

    for _ in range(999):
        if not os.path.exists(img_path):
            return img_path

        if int(img_info["Content-Length"]) != int(len(open(img_path, "rb").read())):
            number = filename[filename.rfind("(") + 1:filename.rfind(")")]
            if number.isdigit and filename[filename.rfind(")") + 1:].lower() in IMG_EXTS:
                file_number = int(number) + 1
                filename = filename.rsplit("(", 1)[0].strip()
            else:
                file_number = 2
                filename = filename.rsplit(".", 1)[0]
            filename = filename.strip() + " (" + str(file_number) + ")" + extension
            if E.organize:
                img_path = os.path.join(
                    folder_name.strip(), filename.strip())
            else:
                img_path = filename.strip()
        else:
            return None


def fetch(url, page=""):
    """sends a http get request and returns html content"""
    logger = logging.getLogger('fetch')
    logger.debug('fetching: %s', url)
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent',
                       'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_4) \
                       AppleWebKit/601.5.17 (KHTML, like Gecko) Version/9.1 Safari/601.5.17')
        req = urllib.request.urlopen(req)
        logger.debug('returning successful request [HTTP status code: %s]', req.getcode())
        return req
    except Exception as err:
        logger.debug('error: %s', err)
        with E.lock:
            E.error_links.append(url + str(page))
        return None


def parse_page(page_url, page_html, page_number):
    page = tistory.Extractor(page_url, page_html, page_number)
    for link in page.get_links():
        E.pic_q.put(link)


def work_page():
    while E.page_q.qsize() > 0:
        page_number = E.page_q.get()
        url = E.url + str(page_number)
        print(url)
        html = fetch(url)
        if html is not None:
            parse_page(url, html, page_number)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

    if len(sys.argv) > 1:
        ARG = sys.argv
    else:
        ARG = 'ty https://ohcori.tistory.com/321 --debug -o -t 6 -f hello/world'.split()

    run(ARG)