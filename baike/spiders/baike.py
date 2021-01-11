# -*- coding: utf-8 -*-
import scrapy
import logging
import urllib
import os
import glob
import re
import pymongo
from scrapy.selector import Selector
# from neo4j.v1 import GraphDatabase
from neo4j import GraphDatabase#  用新版的
import logging
import time

#  创建日志文件
logfile_name = time.ctime(time.time()).replace(' ', '_')
if not os.path.exists('logs/'):
    os.mkdir('logs/')
filename = r'logs/' + logfile_name + '.log'
logging.basicConfig(filename='logs/BaikeSpider.log', filemode='a+',
                    format='%(levelname)s - %(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')

class BaikeSpider(scrapy.Spider):
    print('-' * 20 + 'Spider Running...' + '-' * 20)
    print('Type "Ctrl" + "C" to exit')
    name = 'baike'
    allowed_domains = ['baike.baidu.com']
    start_urls = ['https://baike.baidu.com/item/文汇报']#  从这个网址开始爬取
    #  创建MongoDB实例
    db = pymongo.MongoClient("mongodb://127.0.0.1:27017/")["db_kg"]
    print('MongoDB连接成功')
    #  db_baike表
    db_baike = db['db_baike']
    db_triples = db['db_triples']
    olds = set([item['_id'] for item in db_baike.find({}, {'_id': 1})])
    
    if len(olds) > 0:
        start_urls = ['https://baike.baidu.com/item/'+olds.pop()]
    driver = GraphDatabase.driver(
        "bolt://localhost:7687", auth=("neo4j", "123"))

    def add_node(self, tx, name1, relation, name2):
        tx.run("MERGE (a:Node {name: $name1}) "
                "MERGE (b:Node {name: $name2}) "
                "MERGE (a)-[:" + relation + "]->(b)",
                name1=name1, name2=name2)
        

    def parse(self, response):
        #  正则表达式提取item后面的信息,用于判断有没有爬取过
        item_name = re.sub('/', '', re.sub('https://baike.baidu.com/item/',
                                           '', urllib.parse.unquote(response.url)))
        
        # 爬取过的直接忽视
        if item_name in self.olds: 
            return
        # 将网页内容存入mongodb
        try:
            self.db_baike.insert_one(
                {
                    '_id': item_name,
                    'text': ''.join(response.xpath('//div[@class="main-content"]').xpath('//div[@class="para"]//text()').getall())
                })
        except pymongo.errors.DuplicateKeyError:
            pass
        # 更新爬取过的item集合
        self.olds.add(item_name)
        # 爬取页面内的item
        items = set(response.xpath(
            '//a[contains(@href, "/item/")]/@href').re(r'/item/[A-Za-z0-9%\u4E00-\u9FA5]+'))
        for item in items:
            new_url = 'https://baike.baidu.com'+urllib.parse.unquote(item)
            # print('Spider' + new_url)
            new_item_name = re.sub(
                '/', '', re.sub('https://baike.baidu.com/item/', '', new_url))
            if new_item_name not in self.olds:
                yield response.follow(new_url, callback=self.parse)

        # # 处理三元组
        entity = ''.join(response.xpath(
            '//h1/text()').getall()).replace('/', '')
        attrs = response.xpath(
            '//dt[contains(@class,"basicInfo-item name")]').getall()
        values = response.xpath(
            '//dd[contains(@class,"basicInfo-item value")]').getall()
        if len(attrs) != len(values):
            return
        with self.driver.session() as session:
            try:
                # print('entity:\n',entity)
                # print('attrs:\n',attrs)
                # print('values:\n',values)
                # if attrs != [] and values != []:
                for attr, value in zip(attrs, values):
                    # attr
                    temp = Selector(text=attr).xpath(
                        '//dt//text()').getall()
                    attr = ''.join(temp).replace('\xa0', '')
                    # value
                    value = ''.join(Selector(text=value).xpath(
                        '//dd/text()|//dd/a//text()').getall())
                    value = value.replace('\n', '')
                    
                    try:#  存入MongoDB
                        logging.warning(entity+'_'+attr+'_'+value)
                        self.db_triples.insert_one({
                            "_id": entity+'_'+attr+'_'+value,
                            "item_name": entity,
                            "attr": attr,
                            "value": value, }
                        )#  here

                    except pymongo.errors.DuplicateKeyError:
                        pass
                    # print(entity)
                    # print(attr)
                    # print(value)
                    session.write_transaction(
                        self.add_node, entity, attr, value)
                        
                # else:
                #     print("Pass")
            
            #  怀疑，是MERGE的时候由于编码报错，后续的都不存入Neo4j了
            #  求证：除非是特别特殊的外国语言，否则有一些\xa0都能存进去  排除
            
            except Exception:
                logging.error('\n---'.join(attrs) +
                              '\n_________________'+'\n---'.join(values))
