#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# Author: kerlomz <kerlomz@gmail.com>
import io
import re
import cv2
import time
import base64
import functools
import binascii
import datetime
import hashlib
import numpy as np
import tensorflow as tf
from PIL import Image as PIL_Image
from constants import Response, Config
from pretreatment import preprocessing
from config import ModelConfig


class Arithmetic(object):

    @staticmethod
    def minus_operator_handler(formula):
        minus_operators = re.split("-", formula)
        calc_list = re.findall("[0-9]", formula)
        if minus_operators[0] == '':  # 第一值肯定是负号
            calc_list[0] = '-%s' % calc_list[0]
        res = functools.reduce(lambda x, y: float(x) - float(y), calc_list)
        return res

    @staticmethod
    def remove_duplicates(formula):
        formula = formula.replace("++", "+")
        formula = formula.replace("+-", "-")
        formula = formula.replace("-+", "-")
        formula = formula.replace("--", "+")
        formula = formula.replace("- -", "+")
        return formula

    @staticmethod
    def compute_multiply_and_dividend(formula):
        operators = re.findall("[*/]", formula)
        calc_list = re.split("[*/]", formula)
        res = None
        for index, i in enumerate(calc_list):
            if res:
                if operators[index - 1] == "*":
                    res *= float(i)
                elif operators[index - 1] == "/":
                    res /= float(i)
            else:
                res = float(i)
        return res

    @staticmethod
    def handle_special_occasions(plus_and_minus_operators, multiply_and_dividend):
        for index, i in enumerate(multiply_and_dividend):
            i = i.strip()
            if i.endswith("*") or i.endswith("/"):
                multiply_and_dividend[index] = multiply_and_dividend[index] + plus_and_minus_operators[index] + \
                                               multiply_and_dividend[index + 1]
                del multiply_and_dividend[index + 1]
                del plus_and_minus_operators[index]
        return plus_and_minus_operators, multiply_and_dividend

    @staticmethod
    def compute(formula):
        formula = formula.strip("()")
        formula = Arithmetic.remove_duplicates(formula)
        plus_and_minus_operators = re.findall("[+-]", formula)
        multiply_and_dividend = re.split("[+-]", formula)
        if len(multiply_and_dividend[0].strip()) == 0:
            multiply_and_dividend[1] = plus_and_minus_operators[0] + multiply_and_dividend[1]
            del multiply_and_dividend[0]
            del plus_and_minus_operators[0]

        plus_and_minus_operators, multiply_and_dividend = Arithmetic.handle_special_occasions(
            plus_and_minus_operators, multiply_and_dividend
        )
        for index, i in enumerate(multiply_and_dividend):
            if re.search("[*/]", i):
                sub_res = Arithmetic.compute_multiply_and_dividend(i)
                multiply_and_dividend[index] = sub_res

        total_res = None
        for index, item in enumerate(multiply_and_dividend):
            if total_res:
                if plus_and_minus_operators[index - 1] == '+':
                    total_res += float(item)
                elif plus_and_minus_operators[index - 1] == '-':
                    total_res -= float(item)
            else:
                total_res = float(item)
        return total_res

    @staticmethod
    def calc(formula):
        parenthesise_flag = True
        while parenthesise_flag:
            m = re.search("\([^()]*\)", formula)
            if m:
                sub_res = Arithmetic.compute(m.group())
                formula = formula.replace(m.group(), str(sub_res))
            else:
                return Arithmetic.compute(formula)

class ParamUtils(object):

    @staticmethod
    def filter(param):
        if isinstance(param, list) and len(param) > 0 and isinstance(param[0], bytes):
            return param[0].decode()
        return param


class SignUtils(object):

    @staticmethod
    def md5(text):
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    @staticmethod
    def timestamp():
        return int(time.mktime(datetime.datetime.now().timetuple()))


class PathUtils(object):

    @staticmethod
    def get_file_name(path: str):
        if '/' in path:
            return path.split('/')[-1]
        elif '\\' in path:
            return path.split('\\')[-1]
        else:
            return path


class ImageUtils(object):

    def __init__(self, model: ModelConfig):
        self.model = model

    @staticmethod
    def get_bytes_batch(base64_or_bytes):
        response = Response()
        try:
            if isinstance(base64_or_bytes, bytes):
                bytes_batch = [base64_or_bytes]
            elif isinstance(base64_or_bytes, list):
                bytes_batch = [base64.b64decode(i.encode('utf-8')) for i in base64_or_bytes if isinstance(i, str)]
                if not bytes_batch:
                    bytes_batch = [base64.b64decode(i) for i in base64_or_bytes if isinstance(i, bytes)]
            else:
                bytes_batch = base64.b64decode(base64_or_bytes.encode('utf-8')).split(Config.split_flag)
        except binascii.Error:
            return None, response.INVALID_BASE64_STRING
        what_img = [ImageUtils.test_image(i) for i in bytes_batch]
        if None in what_img:
            return None, response.INVALID_IMAGE_FORMAT
        return bytes_batch, response.SUCCESS

    @staticmethod
    def get_image_batch(model: ModelConfig, bytes_batch):
        # Note that there are two return objects here.
        # 1.image_batch, 2.response

        response = Response()

        def load_image(image_bytes):
            data_stream = io.BytesIO(image_bytes)
            pil_image = PIL_Image.open(data_stream)
            rgb = pil_image.split()
            size = pil_image.size

            if len(rgb) > 3 and model.replace_transparent:
                background = PIL_Image.new('RGB', pil_image.size, (255, 255, 255))
                background.paste(pil_image, (0, 0, size[0], size[1]), pil_image)
                pil_image = background
            pil_image = pil_image.convert('L')

            # image = cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2GRAY)
            image = preprocessing(np.asarray(pil_image), model.binaryzation, model.smooth, model.blur).astype(np.float32)
            image = cv2.resize(image, (model.resize[0], model.resize[1]))
            image = image.swapaxes(0, 1)
            return image[:, :, np.newaxis] / 255.

        try:
            image_batch = [load_image(i) for i in bytes_batch]
            return image_batch, response.SUCCESS
        except OSError:
            return None, response.IMAGE_DAMAGE
        except ValueError as _e:
            print(_e)
            return None, response.IMAGE_SIZE_NOT_MATCH_GRAPH

    @staticmethod
    def pil_image(image_bytes):
        data_stream = io.BytesIO(image_bytes)
        pil_image = PIL_Image.open(data_stream).convert('RGB')
        return pil_image

    @staticmethod
    def size_of_image(image_bytes: bytes):
        _null_size = tuple((-1, -1))
        try:
            data_stream = io.BytesIO(image_bytes)
            size = PIL_Image.open(data_stream).size
            return size
        except OSError:
            return _null_size
        except ValueError:
            return _null_size

    @staticmethod
    def test_image(h):
        """JPEG"""
        if h[:3] == b"\xff\xd8\xff":
            return 'jpeg'
        """PNG"""
        if h[:8] == b"\211PNG\r\n\032\n":
            return 'png'
        """GIF ('87 and '89 variants)"""
        if h[:6] in (b'GIF87a', b'GIF89a'):
            return 'gif'
        """TIFF (can be in Motorola or Intel byte order)"""
        if h[:2] in (b'MM', b'II'):
            return 'tiff'
        if h[:2] == b'BM':
            return 'bmp'
        """SGI image library"""
        if h[:2] == b'\001\332':
            return 'rgb'
        """PBM (portable bitmap)"""
        if len(h) >= 3 and \
                h[0] == b'P' and h[1] in b'14' and h[2] in b' \t\n\r':
            return 'pbm'
        """PGM (portable graymap)"""
        if len(h) >= 3 and \
                h[0] == b'P' and h[1] in b'25' and h[2] in b' \t\n\r':
            return 'pgm'
        """PPM (portable pixmap)"""
        if len(h) >= 3 and h[0] == b'P' and h[1] in b'36' and h[2] in b' \t\n\r':
            return 'ppm'
        """Sun raster file"""
        if h[:4] == b'\x59\xA6\x6A\x95':
            return 'rast'
        """X bitmap (X10 or X11)"""
        s = b'#define '
        if h[:len(s)] == s:
            return 'xbm'
        return None
