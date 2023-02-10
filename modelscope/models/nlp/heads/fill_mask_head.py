# Copyright (c) Alibaba, Inc. and its affiliates.
# Copyright 2018 The Google AI Language Team Authors and The HuggingFace Inc. team.
#
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Dict

import torch
import torch.nn.functional as F
from torch import nn
from torch.nn import CrossEntropyLoss
from transformers.activations import ACT2FN

from modelscope.metainfo import Heads
from modelscope.models.base import TorchHead
from modelscope.models.builder import HEADS
from modelscope.outputs import (AttentionFillMaskModelOutput, ModelOutputBase,
                                OutputKeys)
from modelscope.utils.constant import Tasks


@HEADS.register_module(Tasks.fill_mask, module_name=Heads.bert_mlm)
@HEADS.register_module(Tasks.fill_mask, module_name=Heads.fill_mask)
class BertFillMaskHead(TorchHead):

    def __init__(self,
                 hidden_size=768,
                 hidden_act='gelu',
                 layer_norm_eps=1e-12,
                 vocab_size=30522,
                 **kwargs):
        super().__init__(
            hidden_size=hidden_size,
            hidden_act=hidden_act,
            layer_norm_eps=layer_norm_eps,
            vocab_size=vocab_size)
        self.cls = BertOnlyMLMHead(self.config)

    def forward(self,
                inputs: ModelOutputBase,
                attention_mask=None,
                labels=None,
                **kwargs):
        logits = self.cls(inputs.last_hidden_state)
        loss = None
        if labels is not None:
            loss = self.compute_loss(logits, labels)
        return AttentionFillMaskModelOutput(
            loss=loss,
            logits=logits,
            hidden_states=inputs.hidden_states,
            attentions=inputs.attentions,
        )

    def compute_loss(self, logits: torch.Tensor, labels) -> torch.Tensor:
        loss_fct = CrossEntropyLoss()  # -100 index = padding token
        masked_lm_loss = loss_fct(
            logits.view(-1, self.config.vocab_size), labels.view(-1))
        return masked_lm_loss


class BertPredictionHeadTransform(nn.Module):

    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        if isinstance(config.hidden_act, str):
            self.transform_act_fn = ACT2FN[config.hidden_act]
        else:
            self.transform_act_fn = config.hidden_act
        self.LayerNorm = nn.LayerNorm(
            config.hidden_size, eps=config.layer_norm_eps)

    def forward(self, hidden_states):
        hidden_states = self.dense(hidden_states)
        hidden_states = self.transform_act_fn(hidden_states)
        hidden_states = self.LayerNorm(hidden_states)
        return hidden_states


class BertLMPredictionHead(nn.Module):

    def __init__(self, config):
        super().__init__()
        self.transform = BertPredictionHeadTransform(config)

        # The output weights are the same as the input embeddings, but there is
        # an output-only bias for each token.
        self.decoder = nn.Linear(
            config.hidden_size, config.vocab_size, bias=False)

        self.bias = nn.Parameter(torch.zeros(config.vocab_size))

        # Need a link between the two variables so that the bias is correctly resized with `resize_token_embeddings`
        self.decoder.bias = self.bias

    def forward(self, hidden_states):
        hidden_states = self.transform(hidden_states)
        hidden_states = self.decoder(hidden_states)
        return hidden_states


class BertOnlyMLMHead(nn.Module):

    def __init__(self, config):
        super().__init__()
        self.predictions = BertLMPredictionHead(config)

    def forward(self, sequence_output: torch.Tensor) -> torch.Tensor:
        prediction_scores = self.predictions(sequence_output)
        return prediction_scores
