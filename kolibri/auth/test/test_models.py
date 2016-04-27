"""
Tests of the core auth models (Role, Membership, Collection, FacilityUser, DeviceOwner, etc).
"""

from __future__ import absolute_import, print_function, unicode_literals

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from ..constants import role_kinds, collection_kinds
from ..models import FacilityUser, Facility, Classroom, LearnerGroup, Role, Membership, Collection, DeviceOwner
from ..errors import UserDoesNotHaveRoleError, UserHasRoleOnlyIndirectlyThroughHierarchyError, UserIsNotFacilityUser, \
    UserIsMemberOnlyIndirectlyThroughHierarchyError, InvalidRoleKind, UserIsNotMemberError


class CollectionRoleMembershipDeletionTestCase(TestCase):
    """
    Tests that removing users from a Collection deletes the corresponding Role, and that deleting a Collection
    or FacilityUser deletes all associated Roles and Memberships.
    """

    def setUp(self):

        self.facility = Facility.objects.create()

        learner, classroom_coach, facility_admin = self.learner, self.classroom_coach, self.facility_admin = (
            FacilityUser.objects.create(username='foo', facility=self.facility),
            FacilityUser.objects.create(username='bar', facility=self.facility),
            FacilityUser.objects.create(username='baz', facility=self.facility),
        )

        self.facility.add_admin(facility_admin)

        self.cr = Classroom.objects.create(parent=self.facility)
        self.cr.add_coach(classroom_coach)

        self.lg = LearnerGroup.objects.create(parent=self.cr)
        self.lg.add_learner(learner)

        self.device_owner = DeviceOwner.objects.create(username="blah", password="*")

    def test_remove_learner(self):
        self.assertTrue(self.learner.is_member_of(self.lg))
        self.assertTrue(self.learner.is_member_of(self.cr))
        self.assertTrue(self.learner.is_member_of(self.facility))
        self.assertEqual(Membership.objects.filter(user=self.learner, collection=self.lg).count(), 1)

        self.lg.remove_learner(self.learner)

        self.assertFalse(self.learner.is_member_of(self.lg))
        self.assertFalse(self.learner.is_member_of(self.cr))
        self.assertTrue(self.learner.is_member_of(self.facility))  # always a member of one's own facility
        self.assertEqual(Membership.objects.filter(user=self.learner, collection=self.lg).count(), 0)

        with self.assertRaises(UserIsNotMemberError):
            self.lg.remove_learner(self.learner)

    def test_remove_coach(self):
        self.assertTrue(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.lg))
        self.assertTrue(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.cr))
        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.facility))
        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.ADMIN, self.lg))
        self.assertTrue(self.classroom_coach.has_role_for_user(role_kinds.COACH, self.learner))
        self.assertFalse(self.classroom_coach.has_role_for_user(role_kinds.COACH, self.facility_admin))
        self.assertFalse(self.classroom_coach.has_role_for_user(role_kinds.ADMIN, self.learner))
        self.assertEqual(Role.objects.filter(user=self.classroom_coach, kind=role_kinds.COACH, collection=self.cr).count(), 1)

        self.cr.remove_coach(self.classroom_coach)

        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.lg))
        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.cr))
        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.COACH, self.facility))
        self.assertFalse(self.classroom_coach.has_role_for_collection(role_kinds.ADMIN, self.lg))
        self.assertFalse(self.classroom_coach.has_role_for_user(role_kinds.COACH, self.learner))
        self.assertFalse(self.classroom_coach.has_role_for_user(role_kinds.COACH, self.facility_admin))
        self.assertFalse(self.classroom_coach.has_role_for_user(role_kinds.ADMIN, self.learner))
        self.assertEqual(Role.objects.filter(user=self.classroom_coach, kind=role_kinds.COACH, collection=self.cr).count(), 0)

        with self.assertRaises(UserDoesNotHaveRoleError):
            self.cr.remove_coach(self.classroom_coach)

    def test_remove_admin(self):
        self.assertTrue(self.facility_admin.has_role_for_collection(role_kinds.ADMIN, self.lg))
        self.assertTrue(self.facility_admin.has_role_for_collection(role_kinds.ADMIN, self.cr))
        self.assertTrue(self.facility_admin.has_role_for_collection(role_kinds.ADMIN, self.facility))
        self.assertFalse(self.facility_admin.has_role_for_collection(role_kinds.COACH, self.lg))
        self.assertTrue(self.facility_admin.has_role_for_user(role_kinds.ADMIN, self.learner))
        self.assertTrue(self.facility_admin.has_role_for_user(role_kinds.ADMIN, self.facility_admin))
        self.assertTrue(self.facility_admin.has_role_for_user(role_kinds.ADMIN, self.classroom_coach))
        self.assertFalse(self.facility_admin.has_role_for_user(role_kinds.COACH, self.learner))
        self.assertEqual(Role.objects.filter(user=self.facility_admin, kind=role_kinds.ADMIN, collection=self.facility).count(), 1)

        self.facility.remove_admin(self.facility_admin)

        self.assertEqual(Role.objects.filter(user=self.facility_admin, kind=role_kinds.ADMIN, collection=self.facility).count(), 0)

        with self.assertRaises(UserDoesNotHaveRoleError):
            self.facility.remove_admin(self.facility_admin)

    def test_remove_nonexistent_role(self):
        with self.assertRaises(UserDoesNotHaveRoleError):
            self.facility.remove_admin(self.learner)
        with self.assertRaises(UserDoesNotHaveRoleError):
            self.cr.remove_coach(self.learner)

    def test_remove_indirect_admin_role(self):
        """ Trying to remove the admin role for a a Facility admin from a descendant classroom doesn't actually remove anything. """
        with self.assertRaises(UserHasRoleOnlyIndirectlyThroughHierarchyError):
            self.cr.remove_admin(self.facility_admin)

    def test_remove_indirect_membership(self):
        """ Trying to remove a learner's membership from a classroom doesn't actually remove anything. """
        with self.assertRaises(UserIsMemberOnlyIndirectlyThroughHierarchyError):
            self.cr.remove_member(self.learner)

    def test_delete_learner_group(self):
        """ Deleting a LearnerGroup should delete its associated Memberships as well """
        self.assertEqual(Membership.objects.filter(collection=self.lg.id).count(), 1)
        self.lg.delete()
        self.assertEqual(Membership.objects.filter(collection=self.lg.id).count(), 0)

    def test_delete_classroom_pt1(self):
        """ Deleting a Classroom should delete its associated Roles as well """
        self.assertEqual(Role.objects.filter(collection=self.cr.id).count(), 1)
        self.cr.delete()
        self.assertEqual(Role.objects.filter(collection=self.cr.id).count(), 0)

    def test_delete_classroom_pt2(self):
        """ Deleting a Classroom should delete its associated LearnerGroups """
        self.assertEqual(LearnerGroup.objects.count(), 1)
        self.cr.delete()
        self.assertEqual(LearnerGroup.objects.count(), 0)

    def test_delete_facility_pt1(self):
        """ Deleting a Facility should delete associated Roles as well """
        self.assertEqual(Role.objects.filter(collection=self.facility.id).count(), 1)
        self.facility.delete()
        self.assertEqual(Role.objects.filter(collection=self.facility.id).count(), 0)

    def test_delete_facility_pt2(self):
        """ Deleting a Facility should delete Classrooms under it. """
        self.assertEqual(Classroom.objects.count(), 1)
        self.facility.delete()
        self.assertEqual(Classroom.objects.count(), 0)

    def test_delete_facility_pt3(self):
        """ Deleting a Facility should delete *every* Collection under it and associated Roles """
        self.facility.delete()
        self.assertEqual(Collection.objects.count(), 0)
        self.assertEqual(Role.objects.count(), 0)

    def test_delete_facility_user(self):
        """ Deleting a FacilityUser should delete associated Memberships """
        membership = Membership.objects.get(user=self.learner)
        self.learner.delete()
        self.assertEqual(Membership.objects.filter(id=membership.id).count(), 0)


class CollectionRelatedObjectTestCase(TestCase):

    def setUp(self):

        self.facility = Facility.objects.create()

        users = self.users = [FacilityUser.objects.create(
            username="foo%s" % i,
            facility=self.facility,
        ) for i in range(10)]

        self.facility.add_admins(users[8:9])

        self.cr = Classroom.objects.create(parent=self.facility)
        self.cr.add_coaches(users[5:8])

        self.lg = LearnerGroup.objects.create(parent=self.cr)
        self.lg.add_learners(users[0:5])

    def test_get_learner_groups(self):
        self.assertSetEqual({self.lg.pk}, set(lg.pk for lg in self.cr.get_learner_groups()))

    def test_get_classrooms(self):
        self.assertSetEqual({self.cr.pk}, set(cr.pk for cr in self.facility.get_classrooms()))

    def test_get_classroom(self):
        self.assertEqual(self.cr.pk, self.lg.get_classroom().pk)


class CollectionsTestCase(TestCase):

    def setUp(self):
        self.facility = Facility.objects.create()
        self.classroom = Classroom.objects.create(parent=self.facility)

    def test_add_and_remove_admin(self):
        user = FacilityUser.objects.create(username='foo', facility=self.facility)
        self.classroom.add_admin(user)
        self.facility.add_admin(user)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.ADMIN, collection=self.classroom).count(), 1)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.ADMIN, collection=self.facility).count(), 1)
        self.classroom.remove_admin(user)
        self.facility.remove_admin(user)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.ADMIN, collection=self.classroom).count(), 0)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.ADMIN, collection=self.facility).count(), 0)

    def test_add_and_remove_coach(self):
        user = FacilityUser.objects.create(username='foo', facility=self.facility)
        self.classroom.add_coach(user)
        self.facility.add_coach(user)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.COACH, collection=self.classroom).count(), 1)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.COACH, collection=self.facility).count(), 1)
        self.classroom.remove_coach(user)
        self.facility.remove_coach(user)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.COACH, collection=self.classroom).count(), 0)
        self.assertEqual(Role.objects.filter(user=user, kind=role_kinds.COACH, collection=self.facility).count(), 0)

    def test_add_coaches(self):
        user1 = FacilityUser.objects.create(username='foo1', facility=self.facility)
        user2 = FacilityUser.objects.create(username='foo2', facility=self.facility)
        self.classroom.add_coaches([user1, user2])
        self.facility.add_coaches([user1, user2])
        self.assertEqual(Role.objects.filter(kind=role_kinds.COACH, collection=self.classroom).count(), 2)
        self.assertEqual(Role.objects.filter(kind=role_kinds.COACH, collection=self.facility).count(), 2)

    def test_add_admins(self):
        user1 = FacilityUser.objects.create(username='foo1', facility=self.facility)
        user2 = FacilityUser.objects.create(username='foo2', facility=self.facility)
        self.classroom.add_admins([user1, user2])
        self.facility.add_admins([user1, user2])
        self.assertEqual(Role.objects.filter(kind=role_kinds.ADMIN, collection=self.classroom).count(), 2)
        self.assertEqual(Role.objects.filter(kind=role_kinds.ADMIN, collection=self.facility).count(), 2)

    def test_add_classroom(self):
        classroom = Classroom.objects.create(parent=self.facility)
        self.assertEqual(Classroom.objects.count(), 2)
        self.assertEqual(classroom.get_facility(), self.facility)

    def test_add_learner_group(self):
        classroom = Classroom.objects.create(name="blah", parent=self.facility)
        classroom.full_clean()
        LearnerGroup.objects.create(parent=classroom)
        self.assertEqual(LearnerGroup.objects.count(), 1)

    def test_learner(self):
        user = FacilityUser.objects.create(username='foo', facility=self.facility)
        classroom = Classroom.objects.create(parent=self.facility)
        learner_group = LearnerGroup.objects.create(name="blah", parent=classroom)
        learner_group.full_clean()
        learner_group.add_learner(user)
        self.assertEqual(Membership.objects.filter(user=user, collection=learner_group).count(), 1)

    def test_parentless_classroom(self):
        classroom = Classroom(name="myclass")
        # shouldn't be valid, because no parent was specified, and Classrooms can't be the root of the collection tree
        with self.assertRaises(ValidationError):
            classroom.full_clean()
        with self.assertRaises(IntegrityError):
            classroom.save()

    def test_parentless_learnergroup(self):
        group = LearnerGroup(name="mygroup")
        # shouldn't be valid, because no parent was specified, and LearnerGroups can't be the root of the collection tree
        with self.assertRaises(ValidationError):
            group.full_clean()
        with self.assertRaises(IntegrityError):
            group.save()

    def test_facility_with_parent_facility(self):
        with self.assertRaises(IntegrityError):
            Facility.objects.create(name="blah", parent=self.facility)

    def test_create_bare_collection_without_kind(self):
        with self.assertRaises(ValidationError):
            Collection(name="qqq", parent=self.facility).full_clean()


class RoleErrorTestCase(TestCase):

    def setUp(self):
        self.facility = Facility.objects.create()
        self.classroom = Classroom.objects.create(parent=self.facility)
        self.learner_group = LearnerGroup.objects.create(parent=self.classroom)
        self.facility_user = FacilityUser.objects.create(username="blah", password="#", facility=self.facility)
        self.device_owner = DeviceOwner.objects.create(username="blooh", password="#")

    def test_invalid_role_kind(self):
        with self.assertRaises(InvalidRoleKind):
            self.learner_group.add_role(self.facility_user, "blahblahnonexistentroletype")
        with self.assertRaises(InvalidRoleKind):
            self.learner_group.remove_role(self.facility_user, "blahblahnonexistentroletype")


class DeviceOwnerRoleMembershipTestCase(TestCase):

    def setUp(self):
        self.facility = Facility.objects.create()
        self.classroom = Classroom.objects.create(parent=self.facility)
        self.learner_group = LearnerGroup.objects.create(parent=self.classroom)
        self.facility_user = FacilityUser.objects.create(username="blah", password="#", facility=self.facility)
        self.device_owner = DeviceOwner.objects.create(username="blooh", password="#")
        self.device_owner2 = DeviceOwner.objects.create(username="bleeh", password="#")

    def test_deviceowner_is_not_member_of_any_collection(self):
        self.assertFalse(self.device_owner.is_member_of(self.classroom))
        self.assertFalse(self.device_owner.is_member_of(self.facility))
        self.assertFalse(self.device_owner.is_member_of(self.learner_group))

    def test_deviceowner_is_admin_for_everything(self):
        self.assertSetEqual(self.device_owner.get_roles_for_collection(self.classroom), set([role_kinds.ADMIN]))
        self.assertSetEqual(self.device_owner.get_roles_for_collection(self.facility), set([role_kinds.ADMIN]))
        self.assertSetEqual(self.device_owner.get_roles_for_user(self.facility_user), set([role_kinds.ADMIN]))
        self.assertSetEqual(self.device_owner.get_roles_for_user(self.device_owner), set([role_kinds.ADMIN]))
        self.assertSetEqual(self.device_owner.get_roles_for_user(self.device_owner2), set([role_kinds.ADMIN]))
        self.assertTrue(self.device_owner.has_role_for_user([role_kinds.ADMIN], self.facility_user))
        self.assertTrue(self.device_owner.has_role_for_collection([role_kinds.ADMIN], self.facility))

    def test_device_owners_cannot_be_assigned_or_removed_from_roles(self):
        with self.assertRaises(UserIsNotFacilityUser):
            self.classroom.add_admin(self.device_owner)
        with self.assertRaises(UserIsNotFacilityUser):
            self.classroom.remove_admin(self.device_owner)

    def test_device_owners_cannot_be_members(self):
        with self.assertRaises(UserIsNotFacilityUser):
            self.classroom.add_member(self.device_owner)
        with self.assertRaises(UserIsNotFacilityUser):
            self.classroom.remove_member(self.device_owner)


class StringMethodTestCase(TestCase):

    def setUp(self):

        self.facility = Facility.objects.create(name="Arkham")

        learner, classroom_coach, facility_admin = self.learner, self.classroom_coach, self.facility_admin = (
            FacilityUser.objects.create(username='foo', facility=self.facility),
            FacilityUser.objects.create(username='bar', facility=self.facility),
            FacilityUser.objects.create(username='baz', facility=self.facility),
        )

        self.facility.add_admin(facility_admin)

        self.cr = Classroom.objects.create(name="Classroom X", parent=self.facility)
        self.cr.add_coach(classroom_coach)

        self.lg = LearnerGroup.objects.create(name="Oodles of Fun", parent=self.cr)
        self.lg.add_learner(learner)

        self.device_owner = DeviceOwner.objects.create(username="blah", password="*")

    def test_facility_user_str_method(self):
        self.assertEqual(str(self.learner), '"foo"@"Arkham"')

    def test_device_owner_str_method(self):
        self.assertEqual(str(self.device_owner), "blah")

    def test_collection_str_method(self):
        self.assertEqual(str(Collection.objects.filter(kind=collection_kinds.FACILITY)[0]), '"Arkham" (facility)')

    def test_membership_str_method(self):
        self.assertEqual(str(self.learner.membership_set.all()[0]), '"foo"@"Arkham"\'s membership in "Oodles of Fun" (learnergroup)')

    def test_role_str_method(self):
        self.assertEqual(str(self.classroom_coach.role_set.all()[0]), '"bar"@"Arkham"\'s coach role for "Classroom X" (classroom)')

    def test_facility_str_method(self):
        self.assertEqual(str(self.facility), "Arkham")

    def test_classroom_str_method(self):
        self.assertEqual(str(self.cr), "Classroom X")

    def test_learner_group_str_method(self):
        self.assertEqual(str(self.lg), "Oodles of Fun")
