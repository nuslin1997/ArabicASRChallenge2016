#!/usr/bin/env python

# Copyright (C) 2016 Qatar Computing Research Institute, HBKU (author: yzhang)

__author__ = 'Yifan Zhang (yzhang@qf.org.qa)'

import os
import sys
import time
import codecs
from xml.dom import minidom

class Element(object):
  def __init__(self, text, startTime, endTime=None, speaker=None):
    self.text = text
    self.startTime = startTime
    self.endTime = endTime
    self.speaker = speaker

def loadTrs(trsFileName, opts):
  dom = minidom.parse(open(trsFileName, 'r'))
  trans = dom.getElementsByTagName('Trans')[0]
  uid = trans.attributes['audio_filename'].value
  episode = trans.getElementsByTagName('Episode')[0]
  section = episode.getElementsByTagName('Section')[0]
  turn = section.getElementsByTagName('Turn')[0]
  startTime = float(turn.attributes['startTime'].value)
  endTime = float(turn.attributes['endTime'].value)
  elements = []
  needUpdateEndTime = False
  for i in xrange(1, len(turn.childNodes), 2):
    sync = turn.childNodes[i]
    startTime = float(sync.attributes['time'].value)
    textNode = turn.childNodes[i+1]
    assert textNode.nodeType == textNode.TEXT_NODE
    text = textNode.data.strip()
    e = Element(text=text, startTime=startTime)
    if needUpdateEndTime:
      elements[-1].endTime = startTime
    # for empty segments, we don't need to update endtime
    if text == "" or (opts.skip_ol and text.startswith('##')): 
      needUpdateEndTime = False
      continue
    elements.append(e)
    needUpdateEndTime = True
  elements[-1].endTime = endTime
  return {'id': uid, 'start_time': startTime, 'end_time': endTime, 'turn': elements}

def loadMgb(mgbFileName, opts):
  import xmltodict
  with codecs.open(mgbFileName, 'r', 'utf-8') as fd:
    doc = xmltodict.parse(fd.read())
    speakers = { speaker['@id']:speaker['@name'] for speaker in doc['transcript']['head']['speakers']['speaker']}
    turns = []
    uid = None
    for segment in doc['transcript']['body']['segments']['segment']:
      uid = segment["@id"]
      startTime = float(segment["@starttime"])
      endTime = float(segment["@endtime"])
      speakerName = speakers[segment["@who"]]
      elements = segment['element']
      if isinstance(elements, list):
        text = u' '.join([e['#text'] for e in elements])
      else:
        text = elements['#text']
      turns.append(Element(text, startTime, endTime, speakerName))

    return {'id': uid, 'start_time': 0.0, 'end_time': 0.0, 'turn': turns, 'speaker': set(speakers.values())}


def stm(data):
  out = codecs.getwriter('utf-8')(sys.stdout)
  for e in data['turn']:
    out.write("{} 0 UNKNOWN {:.02f} {:.02f} ".format(data['id'], e.startTime, e.endTime)) 
    out.write(e.text)
    out.write("\n")

def ctm(data):
  """ generate ctm output for test
  """
  out = codecs.getwriter('utf-8')(sys.stdout)
  for e in data['turn']:
    tokens = e.text.split()
    duration = e.endTime - e.startTime
    interval = duration / len(tokens)
    startTime = e.startTime
    for token in tokens:
      out.write("{} 0 {:.02f} {:.02f} ".format(data['id'], startTime, interval))
      out.write(token)
      out.write("\n")

def tra(data, speakers, opts):
  """ generate tra file (as Hamdy generated for training)
  """
  import time
  def format_timestamp(t, mrec_separator=','):
    ms = t - int(t)
    s = time.strftime("%H:%M:%S,", time.gmtime(t))
    return s + "{:02d}".format(int(ms*100))
    
  out = codecs.getwriter('utf-8')(sys.stdout)
  for i,e in enumerate(data['turn']):
    startTime = format_timestamp(e.startTime)
    endTime = format_timestamp(e.endTime)
    if opts.skip_ns and e.text.startswith('@@@'): continue
    tokens = e.text.split()
    if speakers:
      speaker = speakers[i]
      speaker = speaker.replace(u' ', u'-')
    else:
      speaker = "unknown"
    awd = (e.endTime - e.startTime) / len(tokens)
    out.write(u"{}.xml_{}_{}_{} ".format(data['id'], speaker, startTime, endTime))
    out.write(e.text)
    out.write(u"\tWords:{} Correct:{}\tCorrect:100\tIns:0\tDel:0\tWMER:0.0\tPMER:0.0\tAWD:{:2f}\tStart:1\tEnd:1\n".format(len(tokens),
                len(tokens), awd))

def xml(data, xmlFileName):
  from lxml.etree import ElementTree, Element, SubElement, Comment, tostring
  from collections import OrderedDict

  xsi = 'http://www.w3.org/2001/XMLSchema-instance'
  noNamespaceSchemaLocation = "{%s}noNamespaceSchemaLocation" % xsi
  doc = Element('transcript', {noNamespaceSchemaLocation: 'transcript_new.xsd'})
  
  #, { 'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
  #                              'xsi:noNamespaceSchemaLocation': 'transcript_new.xsd' })
  head = SubElement(doc, 'head')
  recording = SubElement(head, 'recording')
  annotations = SubElement(head, 'annotations')
  annotation_id = 'transcript_manual'
  annotation = SubElement(annotations, 'annotation', {'id':annotation_id})
  speakers = SubElement(head, 'speakers')
  speakerSet = data['speaker'] if 'speaker' in data else set() 
  programSet = set()
  body = SubElement(doc, 'body')
  segments = SubElement(body, 'segments', {'annotation_id':annotation_id})
  programId = data['id']
  wordCount = 0
  for i, e in enumerate(data['turn']):
    tokens = e.text.split()
    startTime = e.startTime
    endTime = e.endTime
    averageWordDuration = (e.endTime - e.startTime) / len(tokens)
    speakerName = e.speaker if e.speaker else "{}_unknown_{}".format(programId, i)
    if speakerName not in speakerSet:
      speaker = SubElement(speakers, 'speaker', OrderedDict([('id', speakerName), ('name', speakerName)]))
      speakerSet.add(speaker)
    segment = SubElement(segments, 'segment', OrderedDict([('id',"{}_utt_{}".format(programId,i)),
                                               ('starttime', str(startTime)),
                                               ('endtime', str(endTime)),
                                               ('AWD', "{:2f}".format(averageWordDuration)),
                                               ('PMER', "0.0"),
                                               ('WMER', "0.0"),
                                               ('who', speakerName)]))
    for word in tokens:
      element = SubElement(segment, 'element', OrderedDict([('id',"{}_w{}".format(programId, wordCount)),
                                                ('type','word')]))
      element.text = word
      wordCount += 1

  tree = ElementTree(doc)
  tree.write(xmlFileName, encoding='utf-8', xml_declaration=True, pretty_print=True)


def main(args):
  if args.mgb:
    data = loadMgb(args.trsFileName, args)
  else:
    data = loadTrs(args.trsFileName, args)

  if args.spk:
    speakers = [line.strip() for line in codecs.open(args.spk, 'r', 'utf-8')]
  else:
    speakers = []

  if args.sclite:
    stm(data)
  elif args.ctm:
    ctm(data)
  elif args.tra:
    tra(data, speakers=speakers, opts=args)
  else:
    xml(data, args.xmlFileName)
  

if __name__ == '__main__':
  import argparse

  parser = argparse.ArgumentParser(description='convert Transcriber file to MGB xml')
  parser.add_argument("--id", dest="uid",
                      help="utterance id")
  parser.add_argument("--mgb", dest="mgb", default=False, action='store_true',
                      help="input is mgb format xml")
  parser.add_argument("--spk", dest="spk", type=str, 
                      help="speaker list: each line corresponding to a segment in xml")
  parser.add_argument("--sclite", dest="sclite", default=False, action='store_true',
                      help="output sclite stm file for scoring")
  parser.add_argument("--ctm", dest="ctm", default=False, action='store_true',
                      help="output ctm file for testing")
  parser.add_argument("--tra", dest="tra", default=False, action='store_true',
                      help="output tra file")
  parser.add_argument("--skip-overlaps", dest="skip_ol", default=False, action='store_true',
                      help="skip segments with ###, these are overlapped speech")
  parser.add_argument("--skip-nonspeech", dest="skip_ns", default=False, action='store_true',
                      help="skip segments with @@@, these are non-speech segments")
  parser.add_argument(dest="trsFileName", metavar="trs", type=str)
  parser.add_argument(dest="xmlFileName", metavar="xml", type=str)
  args = parser.parse_args()

  main(args)
