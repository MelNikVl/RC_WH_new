import datetime
import logging
import os
import secrets
import shutil
from typing import Annotated

from fastapi import Depends, File, UploadFile, HTTPException, Form
from pydantic import parse_obj_as
from sqlalchemy import update
from sqlalchemy.orm import Session
from crud.materials import MaterialCRUD
from zeep import Transport, Client

from app.utils.soap import basic, url
from app.utils.utils import response
from app.payload.response import MaterialUploadResponse
from app.utils.auth import AuthUtil, user_dependency
from db.db import get_db
from app.payload.request import MaterialCreateRequest, MaterialGetRequest, MaterialUpdateDescriptionRequest, \
    NewCommentRequest
from models.models import GeoLocation, LogItem, Repair, Comment
from models.models import User, Material
from static_data import main_folder



class MaterialsController:

    # создание карточки актива
    @staticmethod
    async def create(body: MaterialCreateRequest,
                     user: user_dependency,
                     db: Session = Depends(get_db)):

        # logging.info(f"username: , data: {body}")
        material = Material(id=body.id, user_id=user.get("username"), category=body.category, title=body.title,
                            description=body.description, date_time=datetime.datetime.now())

        new_repair = Repair(material_id=body.id,
                            responsible_it_dept_user=user.get("username"),
                            problem_description="создание карточки актива",
                            repair_number=1,
                            date_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            repair_status=False,
                            repair_unique_id=MaterialCRUD.generate_alphanum_random_string(20)
                            )
        db.add(material)
        db.add(new_repair)
        db.commit()
        geolocation = GeoLocation(material_id=material.id, place=body.place, client_mail=user.get("username"),
                                  status="хранение", date_time=datetime.datetime.now(), initiator=user.get("username"))
        db.add(geolocation)
        db.commit()
        material.geolocation_id = geolocation.id
        db.commit()

        return parse_obj_as(MaterialUploadResponse, material)

    # получение карточки по айди
    @staticmethod
    async def get(body: MaterialGetRequest,
                  db: Session = Depends(get_db),
                  user: User = Depends(AuthUtil.decode_jwt)):
        material = await MaterialCRUD.get(id=body.id, db=db)
        return response(data=material, status=True)

    # обновление описания карточки
    @staticmethod
    async def update_description(body: MaterialUpdateDescriptionRequest,
                                 db: Session = Depends(get_db),
                                 user: User = Depends(AuthUtil.decode_jwt)):
        logging.info(f"username: , data: {body}")
        material = await MaterialCRUD.update_description(id=body.id, description=body.description, db=db)
        return response(data=material, status=True)

    @staticmethod
    async def get_material(id: str, user: user_dependency):
        if user.get("role"):
            try:
                session = Session()
                session.verify = False
                session.auth = basic
                transport = Transport(session=session)
                client = Client(
                    url,
                    transport=transport)

                resp = client.service.GetEquipmentInfo(EquipmentID=id)
                from zeep import helpers
                _json = helpers.serialize_object(resp, dict)
                # print(_json)
                return _json
            except:
                return response(data=f'Произошла ошибка', status=False)
        else:
            return response(data=f'Недостаточно прав', status=False)

    @staticmethod
    async def add_from_1c(
            user: user_dependency,
            photos: list[UploadFile],
            title: str = Form(),
            category: str = Form(),
            description: str = Form(),
            id: str = Form(),
            db: Session = Depends(get_db)
    ):
        try:

            # Путь к папке назначения
            destination_folder = os.path.join(f'{main_folder}\\photos', str(id))

        # Проверяем, существует ли папка назначения, и создаем ее при необходимости
            os.makedirs(destination_folder, exist_ok=True)

            material = Material(id=id, user_id=user.get("username"), category=category, title=title,
                                description=description, date_time=datetime.datetime.now())

            new_repair = Repair(material_id=id,
                                responsible_it_dept_user=user.get("username"),
                                problem_description="создание карточки актива",
                                repair_number=1,
                                date_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                repair_status=False,
                                repair_unique_id=MaterialCRUD.generate_alphanum_random_string(20)
                                )
            db.add(material)
            db.add(new_repair)
            db.commit()
            geolocation = GeoLocation(material_id=material.id, place="Склад IT", client_mail=user.get("username"),
                                      status="хранение", date_time=datetime.datetime.now(),
                                      initiator=user.get("username"))
            db.add(geolocation)
            db.commit()
            material.geolocation_id = geolocation.id
            db.commit()
            for photo in photos:
                unique_filename = str(secrets.token_hex(4)) + os.path.splitext(photo.filename)[1]
                destination_path = os.path.join(destination_folder, unique_filename)
                with open(destination_path, "wb") as buffer:
                    buffer.write(await photo.read())
        except Exception as e:
            raise HTTPException(status_code=520, detail="Unknown error")
        return response({"text": "Всё прошло успешно"})

    @staticmethod
    async def update_title(title: str,
                           id_of_material: int,
                           user: user_dependency,
                           db: Session = Depends(get_db),
                           ):

        if user.get("role"):
            try:
                stmt = update(Material).where(Material.id == id_of_material).values(title=title)
                db.execute(stmt)
                db.commit()
                return response(data=f'Актив {id_of_material} изменен. Новый тайтл - {title}', status=True)
            except:
                return response(data=f'Такого актива нет', status=False)
        else:
            return response(data=f'Недостаточно прав', status=False)

    # выводим список активов
    @staticmethod
    async def list_of_materials(db: Session = Depends(get_db),
                                user: User = Depends(AuthUtil.decode_jwt)):
        materials = await MaterialCRUD.list_of_materials(db=db)
        return response(data=materials, status=True)

    # удаление актива
    @staticmethod
    async def delete_material(id_for_delete,
                              db: Session = Depends(get_db),
                              user: User = Depends(AuthUtil.decode_jwt)):
        if user.get("role"):
            material = db.query(Material).filter(Material.id == id_for_delete).first()
            db.delete(material)

            geo_material = db.query(GeoLocation).filter(GeoLocation.material_id == id_for_delete).all()
            for i in geo_material:
                db.delete(i)

            repair_material = db.query(Material).filter(Material.id == id_for_delete).all()
            for y in repair_material:
                db.delete(y)

            db.commit()

            try:
                destination_folder = f'{main_folder}\\photos\\{id_for_delete}'
                # Удаляем папку на сервере
                shutil.rmtree(destination_folder)

                # логируем
                create_geo_event = LogItem(kind_table="Активы",
                                           user_id=user["username"],
                                           passive_id=id_for_delete,
                                           modified_cols="удаление фото",
                                           values_of_change=f'папка с фото удалена с сервера',
                                           date_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                           )
                db.add(create_geo_event)
                db.commit()

            except Exception as e:
                # логируем
                create_geo_event = LogItem(kind_table="Расположение активов",
                                           user_id=user["id"],
                                           passive_id=id_for_delete,
                                           modified_cols="удаление",
                                           values_of_change=f'при удалении папки с сервера возникла ошибка - {e}',
                                           date_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                           )
                db.add(create_geo_event)
                db.commit()

            return response(data={"INFO": f'Актив с ID {id_for_delete} удален успешно'}, status=True)
        else:
            return response(data="Недостаточно прав", status=False)

    # эта ебота написана для записи логов просто в файл. Стирать жалко. Может пригодится
    @staticmethod
    async def get_last_update(user: User = Depends(AuthUtil.decode_jwt)):
        if user.get("role"):
            log_file_path = os.path.join(os.path.dirname(__file__), "../log.log")  # Путь к файлу логов

            # Читаем содержимое файла логов
            with open(log_file_path, "r") as file:
                log_content = file.read()

            return log_content
        else:
            return "You don't have permission"

    @staticmethod
    async def upload_photo(material_id,
                           file: UploadFile = File(...),
                           db: Session = Depends(get_db),
                           user: User = Depends(AuthUtil.decode_jwt)):

        # Путь к папке назначения
        destination_folder = os.path.join(f'{main_folder}\\photos', str(material_id))

        # Проверяем, существует ли папка назначения, и создаем ее при необходимости
        os.makedirs(destination_folder, exist_ok=True)

        unique_filename = str(secrets.token_hex(4)) + os.path.splitext(file.filename)[1]
        destination_path = os.path.join(destination_folder, unique_filename)

        # Загружаем файл в папку назначения
        with open(destination_path, "wb") as buffer:
            buffer.write(await file.read())

        # логируем авторизацию
        autorisation_event = LogItem(kind_table="Активы",
                                     user_id=user.get("username"),
                                     passive_id=material_id,
                                     modified_cols="добавление фото или файлов для актива из WEB",
                                     values_of_change=None,
                                     date_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                     )
        db.add(autorisation_event)
        db.commit()

        return response(data={"message": f'Photo successfully added'}, status=True)

    @staticmethod
    async def send_comment(comment: NewCommentRequest, user: user_dependency, db: Session = Depends(get_db)):
        if len(comment.text)<=100:
            new_comment = Comment(material_id=comment.material_id, user_id=user.get("id"), text=comment.text)
            db.add(new_comment)
            db.commit()
            return response({"text":"ok"}, True)
        else:
            return response({"text": "err"}, False)