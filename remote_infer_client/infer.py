#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import logging

from time import sleep

from .version import __version__

from .exceptions import *
from .proto import *

import requests
from . import settings

from modules import shared


logger = logging.getLogger(__name__)


class SdwInferClient:
    """SdwInferClient is the main entry point for interacting with the sd-webui API."""

    def __init__(self, api_key):
        #self.base_url = "http://api.omniinfer.io/v2"
        #self.api_key = api_key
        self.session = requests.Session()

        #if not self.api_key:
        #    raise ValueError("OMNI_API_KEY environment variable not set")

        # eg: {"all": [proto.ModelInfo], "checkpoint": [proto.ModelInfo], "lora": [proto.ModelInfo]}
        self._model_list_cache = None
        self._extra_headers = {}

    def base_url(self, api_path=''):
        provider = shared.opts.data.get("cloud_inference_remote_provider_list", "127.0.0.1:1234")
        if (api_path in ['/controlnet/model_list']):
            return f"http://{provider}"
        return f"http://{provider}/sdapi/v1"

    def set_extra_headers(self, headers: dict):
        self._extra_headers = headers

    def _get(self, api_path, params=None) -> dict:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            #'X-sd-webui-Key': self.api_key,
            #'User-Agent': "omniinfer-python-sdk/{}".format(__version__),
            'Accept-Encoding': 'gzip, deflate',
        }
        headers.update(self._extra_headers)

        logger.debug(f"[GET] params: {params}")

        response = self.session.get(
            self.base_url(api_path) + api_path,
            #headers=headers,
            params=params,
            timeout=settings.DEFAULT_REQUEST_TIMEOUT,
        )

        logger.debug(f"[GET] response: {response.content}")
        if response.status_code != 200:
            logger.error(f"Request failed: {response}")
            raise OmniResponseError(
                f"Request failed with status {response.status_code}")

        return response.json()

    def _post(self, api_path, data) -> dict:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            #'X-sd-webui-Key': self.api_key,
            #'User-Agent': "omniinfer-python-sdk/{}".format(__version__),
            'Accept-Encoding': 'gzip, deflate',
        }
        headers.update(self._extra_headers)

        logger.debug(f"[POST] data: {data}")

        response = self.session.post(
            self.base_url() + api_path,
            headers=headers,
            json=data,
            timeout=settings.DEFAULT_REQUEST_TIMEOUT,
        )

        logger.debug(f"[POST] response: {response.content}")
        if response.status_code != 200:
            logger.error(f"Request failed: {response}")
            raise OmniResponseError(
                f"Request failed with status {response.status_code}")

        return response.json()

    def txt2img(self, request: Txt2ImgRequest) -> Txt2ImgResponse:
        """Asynchronously generate images from request

        Args:
            request (Txt2ImgRequest): The request object containing the text and image generation parameters.

        Returns:
            Txt2ImgResponse: The response object containing the task ID and status URL.
        """
        response = self._post('/txt2img', request.to_dict())

        return Txt2ImgResponse.from_dict(response)

    def progress(self, task_id: str) -> ProgressResponse:
        """Get the progress of a task.

        Args:
            task_id (str): The ID of the task to get the progress for.

        Returns:
            ProgressResponse: The response object containing the progress information for the task.
        """
        res = self._get('/progress')
        response = SdwProgressData.from_dict(res)
        return ProgressResponse(code = ProgressResponseCode.NORMAL,
								data = ProgressData(status = ProgressResponseStatusCode.SUCCESSFUL,
													progress = response.progress,
													eta_relative = response.eta_relative,
													current_images = response.current_images))
        #END progress

        response = self._get('/progress', {
            'task_id': task_id,
        })

        return ProgressResponse.from_dict(response)

    def img2img(self, request: Img2ImgRequest) -> Img2ImgResponse:
        """Asynchronously generate images from request

        Args:
            request (Img2ImgRequest): The request object containing the image and image generation parameters.

        Returns:
            Img2ImgResponse: The response object containing the task ID and status URL.
        """
        response = self._post('/img2img', request.to_dict())

        return Img2ImgResponse.from_dict(response)

    def wait_for_task(self, task_id, wait_for: int = 300, callback: callable = None) -> ProgressResponse:
        """Wait for a task to complete

        This method waits for a task to complete by periodically checking its progress. If the task is not completed within the specified time, an OmniTimeoutError is raised.

        Args:
            task_id (_type_): The ID of the task to wait for.
            wait_for (int, optional): The maximum time to wait for the task to complete, in seconds. Defaults to 300.

        Raises:
            OmniTimeoutError: If the task fails to complete within the specified time.

        Returns:
            ProgressResponse: The response object containing the progress information for the task.
        """
        i = 0

        while i < wait_for:
            logger.info(f"Waiting for task {task_id} to complete")

            progress = self.progress(task_id)

            if callback and callable(callback):
                try:
                    callback(progress)
                except Exception as e:
                    logger.error(f"Task {task_id} progress callback failed: {e}")

            logger.info(
                f"Task {task_id} progress eta_relative: {progress.data.eta_relative}")

            if progress.data.status.finished():
                logger.info(f"Task {task_id} completed")
                return progress

            sleep(settings.DEFAULT_POLL_INTERVAL)
            i += 1

        raise OmniTimeoutError(
            f"Task {task_id} failed to complete in {wait_for} seconds")

    def sync_txt2img(self, request: Txt2ImgRequest, download_images=True, callback: callable = None) -> ProgressResponse:
        """Synchronously generate images from request, optionally download images

        This method generates images synchronously from the given request object. If download_images is set to True, the generated images will be downloaded.

        Args:
            request (Txt2ImgRequest): The request object containing the input text and other parameters.
            download_images (bool, optional): Whether to download the generated images. Defaults to True.

        Raises:
            OmniResponseError: If the text to image generation fails.

        Returns:
            ProgressResponse: The response object containing the task status and generated images.
        """
        request_ = request.to_dict()
        request_['override_settings'] = {}
        request_['override_settings']['sd_model_checkpoint'] = request.model_name
        request_['override_settings']['CLIP_stop_at_last_layers'] = request.clip_skip
        request_['override_settings']['randn_source']           = shared.opts.randn_source
        request_['override_settings']['token_merging_ratio']    = shared.opts.token_merging_ratio
        request_['override_settings']['token_merging_ratio_hr'] = shared.opts.token_merging_ratio_hr
        request_['override_settings']['eta_noise_seed_delta']   = shared.opts.eta_noise_seed_delta
        alwayson_scripts = {}
        if request.controlnet_units is not None:
            cna = request_['controlnet_units']
            del request_['controlnet_units']
            for i in range(len(cna)):
                cna[i]['enabled'] = True
                cna[i]['image'] = cna[i]['input_image']
                del cna[i]['input_image']
            alwayson_scripts['ControlNet'] = { 'args' : cna }
        if request.roop_units is not None:
            alwayson_scripts['ReActor'] = { 'args' : request_['roop_units'] }
            del request_['roop_units']

        request_['alwayson_scripts'] = alwayson_scripts
        request_['do_not_save_grid'] = True
        request_['send_images'] = True
        request_['save_images'] = False
        #print(request_)
        response_ = self._post('/txt2img', request_)
        response = SdwTxt2ImgResponse.from_dict(response_)

        task_id = ''
        res = self.progress(task_id)
        if callback and callable(callback):
            try:
                callback(res)
            except Exception as e:
                logger.error(f"Task {task_id} progress callback failed: {e}")
        res.data.imgs = response.images
        if download_images:
            res.data.imgs_bytes = response.images
        return res
        #END sync_txt2img

        response = self.txt2img(request)

        if response.data is None:
            raise OmniResponseError(f"Text to Image generation failed with response {response.msg}, code: {response.code}")

        res = self.wait_for_task(response.data.task_id, callback=callback)
        if download_images:
            res.download_images()
        return res

    def sync_img2img(self, request: Img2ImgRequest, download_images=True, callback: callable = None) -> ProgressResponse:
        """Synchronously generate images from request, optionally download images

        Args:
            request (Img2ImgRequest): The request object containing the input image and other parameters.
            download_images (bool, optional): Whether to download the generated images. Defaults to True.

        Returns:
            ProgressResponse: The response object containing the task status and generated images.
        """
        response = self.img2img(request)

        if response.data is None:
            raise OmniResponseError(f"Image to Image generation failed with response {response.msg}, code: {response.code}")

        res = self.wait_for_task(response.data.task_id, callback=callback)
        if download_images:
            res.download_images()
        return res

    def sync_upscale(self, request: UpscaleRequest, download_images=True, callback: callable = None) -> ProgressResponse:
        """Syncronously upscale image from request, optionally download images

        Args:
            request (UpscaleRequest): _description_
            download_images (bool, optional): _description_. Defaults to True.

        Returns:
            ProgressResponse: _description_
        """
        response = self.upscale(request)

        if response.data is None:
            raise OmniResponseError(f"Upscale failed with response {response.msg}, code: {response.code}")

        res = self.wait_for_task(response.data.task_id, callback=callback)
        if download_images:
            res.download_images()
        return res

    def upscale(self, request: UpscaleRequest) -> UpscaleResponse:
        """Upscale image

        This method sends a request to the sd-webui API to upscale an image using the specified parameters.

        Args:
            request (UpscaleRequest): An object containing the input image and other parameters.

        Returns:
            UpscaleResponse: An object containing the task status and the URL of the upscaled image.
        """
        response = self._post('/upscale', request.to_dict())

        return UpscaleResponse.from_dict(response)

    def models(self, refresh=False) -> ModelList:
        """Get list of models

        This method retrieves a list of models available in the sd-webui API. If the list has already been retrieved and
        `refresh` is False, the cached list will be returned. Otherwise, a new request will be made to the API to
        retrieve the list.

        Args:
            refresh (bool, optional): If True, a new request will be made to the API to retrieve the list of models.
                If False and the list has already been retrieved, the cached list will be returned. Defaults to False.

        Returns:
            ModelList: A list of models available in the sd-webui API.
        """

        if (self._model_list_cache is None or len(self._model_list_cache) == 0) or refresh:
            res = self._get('/options')
            default_model = SdwOptions.from_dict(res).sd_model_checkpoint

            #res = self._get('/models')
            res = self._get('/sd-models')

            # TODO: fix this
            #res_controlnet = self._get(
            #    '/models', params={'type': 'controlnet'})
            #res_vae = self._get('/models', params={'type': 'vae'})

            tmp = []
            #tmp.extend(MoodelsResponse.from_dict(res).data.models)
            #tmp.extend(MoodelsResponse.from_dict(res_controlnet).data.models)
            #tmp.extend(MoodelsResponse.from_dict(res_vae).data.models)
            tmp.extend(SdwModelInfoCheckpoint.from_list(res))

            # In future /models maybe return all models, so we need to filter out duplicates
            tmp_set = set()
            models = []
            for m in tmp:
                #if m.sd_name not in tmp_set:
                #    tmp_set.add(m.sd_name)
                #    models.append(m)
                if m.model_name not in tmp_set:
                    tmp_set.add(m.model_name)
                    #print(m.title, 1 if m.title == default_model else 0)
                    models.append(ModelInfo(sd_name=m.title, name=m.model_name, hash=m.hash, type=m.type, civitai_version_id=0,
                                            civitai_download_count=1 if m.title == default_model else 0)) #TODO

            tmp = []
            res_lora = self._get('/loras')
            tmp.extend(SdwModelInfoLora.from_list(res_lora))
            res_upscaler = self._get('/upscalers')
            tmp.extend(SdwModelInfoUpscaler.from_list(res_upscaler))
            for m in tmp:
                if m.name not in tmp_set:
                    tmp_set.add(m.name)
                    models.append(ModelInfo(sd_name=m.name, name=m.name, hash=m.hash, type=m.type, civitai_version_id=0))

            res_embedding = self._get('/embeddings')
            for n in res_embedding['loaded']:
                if n not in tmp_set:
                    tmp_set.add(n)
                    models.append(ModelInfo(sd_name=n, name=n, hash='0', type=ModelType.TEXT_INVERSION, civitai_version_id=0))

            res_controlnet = self._get('/controlnet/model_list')
            for n in res_controlnet['model_list']:
                if n not in tmp_set:
                    tmp_set.add(n)
                    models.append(ModelInfo(sd_name=n, name=n, hash='0', type=ModelType.CONTROLNET, civitai_version_id=0))

            self._model_list_cache = ModelList(models)

        return self._model_list_cache
