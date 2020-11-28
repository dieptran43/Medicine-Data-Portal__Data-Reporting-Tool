from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework import status
from rest_framework import mixins
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from api.helpers.custom_permissions import IsAdmin, IsPartner
from django.core.mail import send_mail
from django.template.loader import render_to_string, get_template
from django.utils.html import strip_tags
from api.models import (
    User,Partner,PartnerSerializer,
    Product,ActiveProduct,Stage,
    Quarter,ProductQuarter,ProductQuarterDate,ProductNotes,
    TemplateMessage,TemplateSubmissionSerializer
)

import datetime, os
from django.template.defaultfilters import date
from MPP_API.settings import FROM_EMAIL_ID


class PDTView(APIView):

    permission_classes = [IsAuthenticated, IsPartner]

    def get(self,request):

        partner_id = request.user.id
        
        rows = []
        quarter_order = [] # Required by the frontend to init the column names (i.e. quarters)
        quarter_objects = []
        quarter_editable = {}

        #Get Active Quarter List
        active_quarters = Quarter.objects.filter(is_active=True).order_by('-quarter_id')
        if not active_quarters.exists():
            return Response(status=status.HTTP_204_NO_CONTENT)
        for quarter in active_quarters:
            quarter_order.append(quarter.quarter_name)
            quarter_objects.append(quarter)

        quarter_order.pop(0)
        latest_quarter = quarter_objects.pop(0)

        for each in quarter_order:
            quarter_editable[each] = True
        quarter_editable[quarter_order[-1]] = False
        
        #Get Active Products for that Partner Id
        active_products = ActiveProduct.objects.filter(partner_id=partner_id,is_active=True).order_by('active_product_id')
        if not active_products.exists():
            return Response(status=status.HTTP_204_NO_CONTENT)

        for active_product in active_products:
            
            if active_product.has_last_quarter != None:
                if active_quarters[1].quarter_id > active_product.has_last_quarter:
                    continue

            product = active_product.product_id
            product_status = active_product.status

            product_name = product.product_name
            
            #Get all the quarters assigned to that product
            product_quarters = ProductQuarter.objects.filter(active_product_id=active_product)
            
            #Get all the stages for that product
            stages = Stage.objects.filter(product_id=product).order_by('description')

            flag = 0
            editable = True
            
            for stage in stages:

                if flag != 0:
                    product_status = None
                    editable = False
                
                temp = {
                    "product":product_name,
                    "product_status":product_status,
                    "editable":editable,
                    "stage":stage.description,
                    "product_id":product.product_id,
                    "stage_id":stage.stage_id,
                }
                print(temp)
                flag = 1

                #Get notes for that stage
                notes = ProductNotes.objects.filter(active_product_id=active_product,stage_id=stage).first()
                if notes != None:
                    temp['notes'] = notes.description
                
                for product_quarter in product_quarters:
                    quarter = product_quarter.quarter_id
                    
                    if quarter == latest_quarter:
                        continue

                    if quarter.is_active:

                        quarter_name = quarter.quarter_name

                        #Get the dates
                        product_quarter_date = ProductQuarterDate.objects.filter(stage_id=stage,product_quarter_id=product_quarter).first()
                        
                        if product_quarter_date != None:
                            start_date = product_quarter_date.start_date
                            end_date = product_quarter_date.end_date
                            
                            if start_date != None:
                                start_date = date(start_date,"m/d/Y")
                            if end_date != None:
                                end_date = date(end_date,"m/d/Y")
                            
                            temp["start_date_" + quarter_name] = start_date
                            temp["end_date_" + quarter_name] = end_date
                    
                rows.append(temp)
     

        # Check if new messages from admin
        unread_message_count = TemplateMessage.objects.filter(partner_id=partner_id,template_type='pdt',is_read=False,is_partner_message=False).count()
        
        # Get messages to send to partner. Convert Queryset to List
        messages = TemplateMessage.objects.filter(partner_id=partner_id,template_type='pdt').values().order_by('-template_message_id')
        messages =[message for message in messages]  
        
        # pdt_status = False
        # template_status = TemplateMessage.objects.filter(
        #     partner_id=partner_id,
        #     quarter_id=quarter_objects[0],
        #     is_partner_message=False,
        #     template_type="pdt").last()
        # if template_status != None:
        #     pdt_status = template_status.is_approved
        #     approval_time=template_status.updated_at
        # else:
        #     approval_time=None
        
        # partner_submission = TemplateMessage.objects.filter(
        #     partner_id=partner_id,
        #     quarter_id=quarter_objects[0],
        #     is_partner_message=True,
        #     template_type="pdt").last()
        
        # if partner_submission:
        #     is_submitted=True
        # else:
        #     is_submitted=False
        # if is_submitted == True and pdt_status == False:
        #     is_submitted='Resubmitted'
        #     pdt_status=None
        approval_time = None
        submission_time = None

        last_msg = TemplateMessage.objects.filter(
            partner_id=partner_id,
            quarter_id=quarter_objects[0],
            template_type="pdt").last()
        
        if last_msg:
            if last_msg.is_partner_message == True:
                report_status = 'Submitted'
                submission_time = last_msg.updated_at
            elif last_msg.is_partner_message == False and last_msg.is_approved == True:
                report_status = 'Approved'
                approval_time = last_msg.updated_at
            elif last_msg.is_partner_message == False and last_msg.is_approved == False:
                report_status = 'Rejected'
                approval_time = last_msg.updated_at
        else:
            report_status = 'Not Submitted'
    
        
        pdt_meta = {
            "partner_name":Partner.objects.get(pk=partner_id).company_name,
            "quarter_name":quarter_order[0],
            "report_status":report_status,
            "approval_time":approval_time,
            "submission_time":submission_time
        }

        return Response(data={'pdt_meta':pdt_meta,'quarter_order':quarter_order,'quarter_editable':quarter_editable,'rows':rows,'messages':messages,'unread_message_count':unread_message_count},status=status.HTTP_200_OK)

    
    def post(self,request):

        partner_id = request.user.id

        data = request.data

        active_products = ActiveProduct.objects.filter(partner_id=partner_id,is_active=True)
        if not active_products.exists():
            return Response(status=status.HTTP_204_NO_CONTENT)

        for active_product in active_products:
            product = active_product.product_id
            product_id=str(product.product_id)

            if data.get(product_id,None) == None:
                continue
            
            if data[product_id].get('product_status',None) != None:
                product_status = data[product_id].get('product_status',None)
                active_product.status = product_status

                if product_status == 'APPROVED' or product_status == 'FILED' or product_status == 'DROPPED':
                    active_product.has_last_quarter = Quarter.objects.filter(is_active=True).order_by('-quarter_id')[1].quarter_id

                active_product.save()

            product_quarters = ProductQuarter.objects.filter(active_product_id=active_product)
            stages = Stage.objects.filter(product_id=product)

            for stage in stages:
                stage_id=str(stage.stage_id)

                if data[product_id].get(stage_id,None) == None:
                    continue

                if data[product_id][stage_id].get('notes',None) != None:
                    notes = data[product_id][stage_id].get('notes',None)
                    try:
                        obj = ProductNotes.objects.get(active_product_id=active_product,stage_id=stage)
                        obj.description = notes
                        obj.updated_by = request.user.id
                        obj.save()

                    except ProductNotes.DoesNotExist:
                        ProductNotes.objects.create(
                            active_product_id=active_product,
                            stage_id=stage,
                            description=notes,
                            created_by=request.user.id,
                            updated_by=request.user.id
                        )

                for product_quarter in product_quarters:
                    quarter = product_quarter.quarter_id
                    quarter_name = quarter.quarter_name
                    
                    if data[product_id][stage_id].get(quarter_name,None) == None:
                        continue

                    if quarter.is_active:
                        
                        start_date = data[product_id][stage_id][quarter_name].get('start_date',None)
                        end_date = data[product_id][stage_id][quarter_name].get('end_date',None)
                        
                        try:
                            if start_date != None:
                                start_date = datetime.datetime.strptime(start_date,"%m/%d/%Y").date()
                            if end_date != None:
                                end_date = datetime.datetime.strptime(end_date,"%m/%d/%Y").date()
                        except:
                            return Response(status=status.HTTP_400_BAD_REQUEST)

                        try:
                            obj = ProductQuarterDate.objects.get(stage_id=stage,product_quarter_id=product_quarter)
                            obj.start_date = start_date
                            obj.end_date = end_date
                            obj.updated_by = request.user.id
                            obj.save()

                        except ProductQuarterDate.DoesNotExist:
                            ProductQuarterDate.objects.create(
                                stage_id=stage,
                                product_quarter_id=product_quarter,
                                start_date=start_date,
                                end_date=end_date,
                                created_by=request.user.id,
                                updated_by=request.user.id
                            )
                        
        return Response(data={'Data Posted Successfully'},status=status.HTTP_200_OK)

class PDTSubmissionViewset(viewsets.ModelViewSet):
    
    permission_classes = [IsAuthenticated,IsPartner]
    serializer_class = TemplateSubmissionSerializer
    queryset = TemplateMessage.objects.filter(template_type='pdt',is_partner_message=True)

    def perform_create(self, serializer):
        template_type = 'PDT'
        partner_id=self.request.user.id
        api_link=os.getenv('API_LINK')
        link = str(api_link+'admin/development-timeline/'+str(partner_id)+'/')
        #from_email_id = User.objects.filter(id=self.request.user.id).values_list('email',flat=True)[0]
        from_email_id = FROM_EMAIL_ID
        partner_name = Partner.objects.filter(partner_id=self.request.user.id).values_list('company_name',flat=True)[0]
        to_email_ids = []
        admin_email_ids = User.objects.filter(role='ADMIN').values('email')
        admin_email_ids = [entry for entry in admin_email_ids]
        for email in admin_email_ids:
            to_email_ids.append(email['email'])

        email_subject = str(partner_name.capitalize() + " has submitted " + template_type + " report")

        try:
            message=self.request.data['message']
        except:
            message=None
        
        now = datetime.datetime.now()
        
        disguised_email = partner_name.capitalize() + " <" + from_email_id + ">"

        html_message = render_to_string('partner_submission.html', {'message':message,'partner_name': partner_name.capitalize(),'template_type':template_type,'link':link, 'now':now})
        plain_message = strip_tags(html_message)
        send_mail(email_subject, plain_message, disguised_email, to_email_ids, html_message=html_message)
        
        quarter_order=[]
        q_1_quarter = Quarter.objects.filter(is_active=True).order_by('-quarter_id')[1]
        quarter_name = q_1_quarter.__dict__['quarter_name']

        partner = Partner.objects.filter(partner_id=self.request.user.id)[0]
        serializer.save(partner_id=partner,template_type='pdt',is_partner_message=True, quarter_id=q_1_quarter,quarter_name=quarter_name)

class PDTInboxPartner(APIView):

    permission_classes = [IsAuthenticated]

    def post(self,request):
        unread_messages = TemplateMessage.objects.filter(template_type='pdt',is_partner_message=False,is_read=False)
        unread_messages.update(is_read=True)
        return Response(data={'Read all unread messages'},status=status.HTTP_200_OK)
